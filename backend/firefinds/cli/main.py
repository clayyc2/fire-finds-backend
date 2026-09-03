"""Fire Finds CLI."""

from __future__ import annotations

import argparse
import json
import sys

from firefinds.clients.ebay import EbayClient, EbayCredentialsMissing
from firefinds.clients.randmar import SupplierOrdersDisabled
from firefinds.config import get_settings
from firefinds.services import (
    ingest_live,
    ingest_stub,
    rank_candidates,
    score_all,
)
from firefinds.services_queue import (
    export_listable_json,
    health_check,
    validate_eligible_queue,
)
from firefinds.services_quote import quote_eligible_skus
from firefinds.scoring.shipping import InjectedQuoteProvider
from firefinds.pipelines.snapshot import freeze_shipping_snapshot, snapshot_stamp_from_progress
from firefinds.pipelines.cohorts import split_randmar_cohorts
from firefinds.pipelines.authorize import authorize_and_draft_survivors
from firefinds.discovery.ebay_demand import discover_ebay_demand_first


def cmd_ingest_stub(_args: argparse.Namespace) -> int:
    settings = get_settings()
    count = ingest_stub(settings)
    print(f"ingest-stub: upserted {count} stub products into {settings.db_path}")
    return 0


def cmd_ingest_live(args: argparse.Namespace) -> int:
    settings = get_settings()
    try:
        count = ingest_live(
            settings=settings,
            manufacturer_id=args.manufacturer_id,
        )
    except SupplierOrdersDisabled as exc:
        print(f"ingest-live refused: {exc}", file=sys.stderr)
        return 2
    print(
        f"ingest-live: upserted {count} products into {settings.db_path} "
        f"(read-only; orders gate="
        f"{'ON' if settings.supplier_orders_enabled else 'OFF'})"
    )
    return 0


def cmd_score(_args: argparse.Namespace) -> int:
    settings = get_settings()
    updated = score_all(settings)
    print(f"score: rescored {updated} products in {settings.db_path}")
    return 0


def cmd_rank(args: argparse.Namespace) -> int:
    settings = get_settings()
    rows = rank_candidates(args.n, settings=settings)
    print(json.dumps(rows, indent=2, default=str))
    print(f"# rank: {len(rows)} candidates (top {args.n})", file=sys.stderr)
    return 0


def cmd_order(_args: argparse.Namespace) -> int:
    settings = get_settings()
    if not settings.supplier_orders_enabled:
        print(
            "SUPPLIER_ORDERS_ENABLED is false; refusing to place order",
            file=sys.stderr,
        )
        return 2
    print("Live supplier orders are not implemented", file=sys.stderr)
    return 1


def cmd_ebay_sandbox_status(_args: argparse.Namespace) -> int:
    settings = get_settings()
    client = EbayClient(settings)
    print(json.dumps(client.sandbox_status(), indent=2))
    return 0


def cmd_ebay_compete(args: argparse.Namespace) -> int:
    """Validate eligible SKUs (alias of validate-queue focused on compete)."""
    settings = get_settings()
    quote_provider = None
    if args.inject_ship is not None:
        quote_provider = InjectedQuoteProvider(default_cost=float(args.inject_ship))
    result = validate_eligible_queue(
        settings=settings,
        quote_provider=quote_provider,
        limit=args.limit,
        dry_run=args.dry_run,
        write_drafts=not args.dry_run,
        use_cached_quotes=bool(getattr(args, "use_cached_quotes", False)),
        sleep_sec=getattr(args, "sleep", None),
        resume_quotes=not bool(getattr(args, "no_resume", False)),
    )
    summary = result["summary"]
    print(json.dumps(summary, indent=2, default=str))
    if not summary.get("ebay_credentials_present"):
        print(
            "# eBay credentials missing — official Browse skipped; "
            "rows flagged provisional_public_ebay / needs_official_ebay_validation. "
            "Set EBAY_CLIENT_ID + EBAY_CLIENT_SECRET_FILE when developer approval lands.",
            file=sys.stderr,
        )
    return 0


def cmd_validate_queue(args: argparse.Namespace) -> int:
    return cmd_ebay_compete(args)


def cmd_listable_export(args: argparse.Namespace) -> int:
    settings = get_settings()
    rows = export_listable_json(settings=settings, limit=args.limit)
    print(json.dumps(rows, indent=2, default=str))
    print(f"# listable-export: {len(rows)} rows", file=sys.stderr)
    return 0


def cmd_quote_shipping(args: argparse.Namespace) -> int:
    settings = get_settings()
    quote_provider = None
    if args.inject_ship is not None:
        quote_provider = InjectedQuoteProvider(default_cost=float(args.inject_ship))
    summary = quote_eligible_skus(
        settings=settings,
        quote_provider=quote_provider,
        limit=args.limit,
        sleep_sec=args.sleep,
        resume=not args.no_resume,
        force=args.force,
    )
    print(json.dumps(summary, indent=2, default=str))
    if args.rebuild_queue:
        result = validate_eligible_queue(
            settings=settings,
            quote_provider=quote_provider,
            limit=args.limit,
            dry_run=False,
            write_drafts=True,
            use_cached_quotes=True,
            sleep_sec=0.0,
            resume_quotes=True,
        )
        print(json.dumps(result["summary"], indent=2, default=str))
        summary = result["summary"]
    return 0


def cmd_health(_args: argparse.Namespace) -> int:
    settings = get_settings()
    report = health_check(settings=settings)
    print(json.dumps(report, indent=2, default=str))
    # Non-zero if live gates accidentally enabled
    if report["gates"].get("LIVE_LISTINGS_ENABLED") or report["gates"].get(
        "SUPPLIER_ORDERS_ENABLED"
    ):
        print("# WARNING: a live gate is ON", file=sys.stderr)
        return 3
    return 0


def cmd_freeze_shipping_snapshot(args: argparse.Namespace) -> int:
    settings = get_settings()
    import subprocess
    from pathlib import Path as _P
    import json as _json

    git_head = None
    try:
        git_head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(_P(settings.db_path).resolve().parents[1]),
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        git_head = None
    snap_id = args.snapshot_id
    if not snap_id:
        progress_path = _P(settings.db_path).parent / "shipping_quote_progress.json"
        progress = {}
        if progress_path.is_file():
            progress = _json.loads(progress_path.read_text(encoding="utf-8"))
        snap_id = snapshot_stamp_from_progress(progress)
    meta = freeze_shipping_snapshot(
        settings=settings, snapshot_id=snap_id, git_head=git_head
    )
    print(json.dumps(meta, indent=2, default=str))
    return 0


def cmd_split_cohorts(args: argparse.Namespace) -> int:
    settings = get_settings()
    result = split_randmar_cohorts(
        settings=settings, snapshot_id=args.snapshot_id
    )
    print(json.dumps(result["summary"], indent=2, default=str))
    return 0


def cmd_authorize_drafts(args: argparse.Namespace) -> int:
    settings = get_settings()
    result = authorize_and_draft_survivors(
        settings=settings, snapshot_id=args.snapshot_id
    )
    print(json.dumps(result["summary"], indent=2, default=str))
    return 0


def cmd_ebay_demand_discover(args: argparse.Namespace) -> int:
    settings = get_settings()
    result = discover_ebay_demand_first(
        settings=settings, snapshot_id=args.snapshot_id
    )
    print(json.dumps(result["summary"], indent=2, default=str))
    return 0


def cmd_pipeline_freeze_split_draft(args: argparse.Namespace) -> int:
    """A+B+C+D convenience: freeze → split → authorize drafts → scaffold EDF."""
    settings = get_settings()
    import subprocess
    from pathlib import Path as _P
    import json as _json

    git_head = None
    try:
        git_head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(_P(settings.db_path).resolve().parents[1]),
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        git_head = None
    progress_path = _P(settings.db_path).parent / "shipping_quote_progress.json"
    progress = {}
    if progress_path.is_file():
        progress = _json.loads(progress_path.read_text(encoding="utf-8"))
    snap_id = args.snapshot_id or snapshot_stamp_from_progress(progress)
    freeze = freeze_shipping_snapshot(
        settings=settings, snapshot_id=snap_id, git_head=git_head
    )
    cohorts = split_randmar_cohorts(settings=settings, snapshot_id=snap_id)
    drafts = authorize_and_draft_survivors(settings=settings, snapshot_id=snap_id)
    edf = discover_ebay_demand_first(settings=settings, snapshot_id=snap_id)
    out = {
        "snapshot_id": snap_id,
        "freeze": freeze,
        "cohorts": cohorts["summary"],
        "drafts": drafts["summary"],
        "ebay_demand_first": edf["summary"],
    }
    print(json.dumps(out, indent=2, default=str))
    return 0



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="firefinds",
        description="Fire Finds interim backend CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser(
        "ingest-stub", help="Load deterministic stub catalog into SQLite"
    )
    p_ingest.set_defaults(func=cmd_ingest_stub)

    p_live = sub.add_parser(
        "ingest-live",
        help="Read-only live Randmar catalog ingest + score into SQLite",
    )
    p_live.add_argument(
        "--manufacturer-id",
        default=None,
        help="Optional manufacturerId query for Products/JSON",
    )
    p_live.set_defaults(func=cmd_ingest_live)

    p_score = sub.add_parser("score", help="Rescore all products in SQLite")
    p_score.set_defaults(func=cmd_score)

    p_rank = sub.add_parser("rank", help="Print top N passing candidates as JSON")
    p_rank.add_argument("-n", type=int, default=10, help="Number of candidates")
    p_rank.set_defaults(func=cmd_rank)

    p_order = sub.add_parser(
        "place-order", help="Place supplier order (gated; default OFF)"
    )
    p_order.set_defaults(func=cmd_order)

    p_status = sub.add_parser(
        "ebay-sandbox-status", help="Show eBay sandbox/gates/credentials presence"
    )
    p_status.set_defaults(func=cmd_ebay_sandbox_status)

    def _add_queue_args(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Optional process limit (debug); default = ALL eligible",
        )
        p.add_argument(
            "--dry-run",
            action="store_true",
            help="Compute without persisting ranked_queue / drafts",
        )
        p.add_argument(
            "--inject-ship",
            type=float,
            default=None,
            help=(
                "TEST ONLY: inject a resolved shipping cost (CAD) for all SKUs. "
                "Production must use Randmar quote endpoints."
            ),
        )
        p.add_argument(
            "--sleep",
            type=float,
            default=None,
            help="Seconds between destination quote calls (rate limit)",
        )
        p.add_argument(
            "--use-cached-quotes",
            action="store_true",
            help="Use persisted shipping_quotes (p75) instead of live quoting",
        )
        p.add_argument(
            "--no-resume",
            action="store_true",
            help="Re-quote even if shipping_quotes already has all dests",
        )

    p_compete = sub.add_parser(
        "ebay-compete",
        help="Validate eligible SKUs (competition + shipping + listable queue)",
    )
    _add_queue_args(p_compete)
    p_compete.set_defaults(func=cmd_ebay_compete)

    p_vq = sub.add_parser(
        "validate-queue",
        help="Alias of ebay-compete: full eligible validation + ranked queue",
    )
    _add_queue_args(p_vq)
    p_vq.set_defaults(func=cmd_validate_queue)

    p_quote = sub.add_parser(
        "quote-shipping",
        help=(
            "Quote representative dests for eligible SKUs (p75 shipping); "
            "checkpoint/resume; never Process"
        ),
    )
    p_quote.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional SKU cap for testing; default = ALL eligible",
    )
    p_quote.add_argument(
        "--sleep",
        type=float,
        default=None,
        help="Seconds between dest quote calls (default SHIP_QUOTE_SLEEP_SEC)",
    )
    p_quote.add_argument(
        "--no-resume",
        action="store_true",
        help="Ignore checkpoint and re-quote",
    )
    p_quote.add_argument(
        "--force",
        action="store_true",
        help="Re-quote SKUs even if dest quotes already persist",
    )
    p_quote.add_argument(
        "--rebuild-queue",
        action="store_true",
        help="After quoting, rebuild ranked_queue using cached p75 quotes",
    )
    p_quote.add_argument(
        "--inject-ship",
        type=float,
        default=None,
        help="TEST ONLY: inject a resolved shipping cost (CAD) for all dests",
    )
    p_quote.set_defaults(func=cmd_quote_shipping)

    p_export = sub.add_parser(
        "listable-export",
        help="Export ranked_queue JSON (optional soft --limit for display only)",
    )
    p_export.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Soft display limit only; does not truncate persisted queue",
    )
    p_export.set_defaults(func=cmd_listable_export)

    p_health = sub.add_parser(
        "health", help="DB / gates / secrets-presence / last-ingest check"
    )
    p_health.set_defaults(func=cmd_health)


    p_freeze = sub.add_parser(
        "freeze-shipping-snapshot",
        help="Freeze immutable shipping-complete snapshot under data/snapshots/",
    )
    p_freeze.add_argument(
        "--snapshot-id",
        default=None,
        help="Override stamp YYYYMMDD_HHMM (default from progress.updated_at Edmonton)",
    )
    p_freeze.set_defaults(func=cmd_freeze_shipping_snapshot)

    p_split = sub.add_parser(
        "split-cohorts",
        help="Split ranked_queue into SAFE_NATIONWIDE / DESTINATION_SENSITIVE + quarantine",
    )
    p_split.add_argument("--snapshot-id", required=True)
    p_split.set_defaults(func=cmd_split_cohorts)

    p_auth = sub.add_parser(
        "authorize-drafts",
        help="MAP/channel authorize survivors and write drafts (never publish)",
    )
    p_auth.add_argument("--snapshot-id", required=True)
    p_auth.set_defaults(func=cmd_authorize_drafts)

    p_edf = sub.add_parser(
        "ebay-demand-discover",
        help="EBAY_DEMAND_FIRST discovery (provisional until official eBay keys)",
    )
    p_edf.add_argument("--snapshot-id", required=True)
    p_edf.set_defaults(func=cmd_ebay_demand_discover)

    p_pipe = sub.add_parser(
        "pipeline-freeze-split-draft",
        help="Freeze snapshot + split cohorts + authorize drafts + scaffold EDF",
    )
    p_pipe.add_argument("--snapshot-id", default=None)
    p_pipe.set_defaults(func=cmd_pipeline_freeze_split_draft)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

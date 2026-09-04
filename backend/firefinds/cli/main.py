"""Fire Finds CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

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
from firefinds.discovery.ebay_demand import (
    discover_ebay_demand_first,
    ingest_provisional_demand_matches,
)
from firefinds.listings.creative_batch import batch_write_creative_drafts
from firefinds.sku_record.metrics import (
    export_learning_comparison,
    get_sku_record,
    upsert_sku_metrics,
)
from firefinds.sku_record.dry_run import run_dry_run_sku
from firefinds.services_images import backfill_safe_nationwide_images
from firefinds.ops.exceptions import list_exceptions, rule_catalog, scan_exceptions
from firefinds.ops.ready_sku_qa import run_ready_sku_qa


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




def cmd_sku_record(args: argparse.Namespace) -> int:
    settings = get_settings()
    if args.sku_command == "upsert-metrics":
        metrics: dict = {}
        if args.pipeline_source:
            metrics["pipeline_source"] = args.pipeline_source
        if args.match_confidence:
            metrics["match_confidence"] = args.match_confidence
        if args.creative_version_id:
            metrics["creative_version_id"] = args.creative_version_id
        if args.creative_variant:
            metrics["creative_variant"] = args.creative_variant
        if args.ab_assignment:
            metrics["ab_assignment"] = args.ab_assignment
        if args.comparison_cohort_id:
            metrics["comparison_cohort_id"] = args.comparison_cohort_id
        if args.demand_evidence_refs:
            metrics["demand_evidence_refs"] = json.loads(args.demand_evidence_refs)
        if args.competition_snapshot_flags:
            metrics["competition_snapshot_flags"] = json.loads(
                args.competition_snapshot_flags
            )
        if args.asset_paths:
            metrics["asset_paths"] = json.loads(args.asset_paths)
        if args.metrics_json:
            metrics.update(json.loads(args.metrics_json))
        # Nullable marketplace numerics
        for key in (
            "impressions",
            "ctr",
            "conversion_rate",
            "sales_units",
            "contribution_profit_realized",
            "cancellations",
            "returns",
            "time_to_first_sale",
            "sell_through",
        ):
            val = getattr(args, key, None)
            if val is not None:
                metrics[key] = val
        record = upsert_sku_metrics(
            args.sku, metrics, settings=settings, source="cli.sku-record"
        )
        print(json.dumps(record["metrics"], indent=2, default=str))
        return 0
    if args.sku_command == "get":
        record = get_sku_record(args.sku, settings=settings)
        print(json.dumps(record, indent=2, default=str))
        return 0
    if args.sku_command == "export-learning":
        out = args.output
        if out is None:
            out = str(
                Path(settings.db_path).parent
                / "learning_exports"
                / "comparison.json"
            )
        payload = export_learning_comparison(
            settings=settings,
            comparison_cohort_id=args.comparison_cohort_id,
            pipeline_source=args.pipeline_source,
            limit=args.limit,
            export_path=out,
        )
        print(json.dumps({"count": payload["count"], "export_path": payload.get("export_path")}, indent=2))
        return 0
    print(f"unknown sku-record subcommand: {args.sku_command}", file=sys.stderr)
    return 2


def cmd_dry_run_sku(args: argparse.Namespace) -> int:
    settings = get_settings()
    try:
        report = run_dry_run_sku(
            sku=args.sku,
            settings=settings,
            snapshot_id=args.snapshot_id,
            include_ai_twin=not args.no_ai_twin,
        )
    except (RuntimeError, ValueError, KeyError) as exc:
        print(f"dry-run-sku failed: {exc}", file=sys.stderr)
        return 2
    # Compact stdout summary + path
    summary = {
        "sku": report["sku"],
        "report_path": report.get("report_path"),
        "gate_pass": report["backend_gates"]["pass"],
        "listing_status": report.get("listing_status"),
        "order_status": report.get("order_status"),
        "stages": [s["stage"] for s in report["stages"]],
    }
    print(json.dumps(summary, indent=2, default=str))
    return 0 if report["backend_gates"]["pass"] else 1



def cmd_ebay_demand_ingest(args: argparse.Namespace) -> int:
    """Ingest provisional demand matches/signals JSON into EBAY_DEMAND_FIRST."""
    settings = get_settings()
    try:
        result = ingest_provisional_demand_matches(
            signals_path=args.signals_file,
            snapshot_id=args.snapshot_id,
            settings=settings,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ebay-demand-ingest failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result["summary"], indent=2, default=str))
    return 0


def cmd_batch_creative_drafts(args: argparse.Namespace) -> int:
    """Batch-write optimized creative drafts into cohort-separated dirs."""
    settings = get_settings()
    cohorts = None
    if args.cohort:
        cohorts = [args.cohort]
    try:
        result = batch_write_creative_drafts(
            settings=settings,
            snapshot_id=args.snapshot_id,
            cohorts=cohorts,
            include_ai_twin=not args.no_ai_twin,
            limit=args.limit,
        )
    except (RuntimeError, ValueError, KeyError) as exc:
        print(f"batch-creative-drafts failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result["summary"], indent=2, default=str))
    return 0





def cmd_ops_exceptions(args: argparse.Namespace) -> int:
    """Deterministic Ops exception scan / list (no AI)."""
    settings = get_settings()
    if args.ops_command == "scan":
        summary = scan_exceptions(
            settings=settings,
            snapshot_id=args.snapshot_id,
            limit=args.limit,
            ingest_streak_threshold=args.ingest_streak_threshold,
            apply_pause=not args.no_pause,
        )
        print(json.dumps(summary, indent=2, default=str))
        return 0
    if args.ops_command == "list":
        status = None if (args.status or "").strip().lower() == "all" else args.status
        rows = list_exceptions(
            settings=settings,
            status=status,
            rule_code=args.rule,
            sku=args.sku,
            limit=args.limit,
        )
        print(json.dumps(rows, indent=2, default=str))
        print(f"# ops-exceptions list: {len(rows)} rows", file=sys.stderr)
        return 0
    if args.ops_command == "rules":
        print(json.dumps(rule_catalog(), indent=2))
        return 0
    print(f"unknown ops-exceptions subcommand: {args.ops_command}", file=sys.stderr)
    return 2

def cmd_backfill_images(args: argparse.Namespace) -> int:
    """Read-only Randmar Product/Images (+ Image/{id} stills) for SAFE_NATIONWIDE."""
    settings = get_settings()
    if settings.live_listings_enabled or settings.supplier_orders_enabled:
        print(
            "Refusing: LIVE_LISTINGS_ENABLED or SUPPLIER_ORDERS_ENABLED is ON",
            file=sys.stderr,
        )
        return 2
    try:
        summary = backfill_safe_nationwide_images(
            settings=settings,
            snapshot_id=args.snapshot_id,
            sleep_sec=args.sleep,
            limit=args.limit,
            resume=not args.no_resume,
            force=args.force,
            download_binaries=not args.urls_only,
            use_token=bool(args.use_token),
        )
    except (RuntimeError, ValueError) as exc:
        print(f"backfill-images failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2, default=str))
    return 0

def cmd_qa_ready(args: argparse.Namespace) -> int:
    """Automated QA across ready/listable SKUs (never publish/order)."""
    settings = get_settings()
    if settings.live_listings_enabled or settings.supplier_orders_enabled:
        print(
            "Refusing: LIVE_LISTINGS_ENABLED or SUPPLIER_ORDERS_ENABLED is ON",
            file=sys.stderr,
        )
        return 2
    cohorts = None
    if args.cohort:
        cohorts = [args.cohort]
    elif args.all_listable_cohorts:
        cohorts = None  # handled below
    preferred = ("SAFE_NATIONWIDE", "DESTINATION_SENSITIVE")
    if args.all_listable_cohorts:
        # Scan every listable_pass row regardless of cohort tag
        from firefinds.db.schema import init_db
        conn = init_db(settings.db_path)
        rows = conn.execute(
            "SELECT DISTINCT cohort FROM products WHERE listable_pass=1"
        ).fetchall()
        cohorts = sorted({str(r[0]) for r in rows if r[0]})
        conn.close()
    report = run_ready_sku_qa(
        settings=settings,
        cohorts=cohorts or preferred,
        listable_only=not args.include_non_listable,
        write_reports=not args.no_write,
        report_stem=args.report_stem,
        top_n=args.top,
    )
    summary = {
        "universe_count": report["universe_count"],
        "skus_passing": report["skus_passing"],
        "skus_failing": report["skus_failing"],
        "fail_counts_by_rule": report["fail_counts_by_rule"],
        "report_json": report.get("report_json"),
        "report_md": report.get("report_md"),
        "listable_growth": {
            k: report.get("listable_growth", {}).get(k)
            for k in (
                "prior_preferred_listable",
                "current_preferred_listable",
                "current_total_listable_pass",
                "delta_total_vs_prior_preferred",
            )
        }
        if report.get("listable_growth")
        else None,
    }
    print(json.dumps(summary, indent=2, default=str))
    return 1 if report["skus_failing"] else 0


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

    p_sku = sub.add_parser(
        "sku-record",
        help="Shared SKU measurable outcomes (upsert-metrics / get / export-learning)",
    )
    sku_sub = p_sku.add_subparsers(dest="sku_command", required=True)

    p_up = sku_sub.add_parser(
        "upsert-metrics", help="Write research/creative/marketplace/learning fields"
    )
    p_up.add_argument("--sku", required=True)
    p_up.add_argument("--pipeline-source", choices=["RANDMAR_FIRST", "EBAY_DEMAND_FIRST"])
    p_up.add_argument(
        "--match-confidence", choices=["A_EXACT", "B_VARIANT", "C_SUBSTITUTE"]
    )
    p_up.add_argument("--creative-version-id")
    p_up.add_argument(
        "--creative-variant", choices=["ORIGINAL_SUPPLIER", "AI_ENHANCED"]
    )
    p_up.add_argument("--ab-assignment")
    p_up.add_argument("--comparison-cohort-id")
    p_up.add_argument("--demand-evidence-refs", help="JSON list/object")
    p_up.add_argument("--competition-snapshot-flags", help="JSON object")
    p_up.add_argument("--asset-paths", help="JSON list of paths")
    p_up.add_argument("--metrics-json", help="JSON object of extra allowed keys")
    p_up.add_argument("--impressions", type=float, default=None)
    p_up.add_argument("--ctr", type=float, default=None)
    p_up.add_argument("--conversion-rate", type=float, default=None)
    p_up.add_argument("--sales-units", type=float, default=None)
    p_up.add_argument("--contribution-profit-realized", type=float, default=None)
    p_up.add_argument("--cancellations", type=int, default=None)
    p_up.add_argument("--returns", type=int, default=None)
    p_up.add_argument("--time-to-first-sale", type=float, default=None)
    p_up.add_argument("--sell-through", type=float, default=None)
    p_up.set_defaults(func=cmd_sku_record)

    p_get = sku_sub.add_parser("get", help="Show SKU record + measurable outcomes")
    p_get.add_argument("--sku", required=True)
    p_get.set_defaults(func=cmd_sku_record)

    p_exp = sku_sub.add_parser(
        "export-learning",
        help="Export measurable outcomes for pipeline/creative A/B learning",
    )
    p_exp.add_argument("--comparison-cohort-id", default=None)
    p_exp.add_argument("--pipeline-source", default=None)
    p_exp.add_argument("--limit", type=int, default=None)
    p_exp.add_argument("--output", default=None, help="JSON export path")
    p_exp.set_defaults(func=cmd_sku_record)

    p_dry = sub.add_parser(
        "dry-run-sku",
        help="Simulate full SKU E2E (research→creative→gates→SIMULATED listing/order)",
    )
    p_dry.add_argument(
        "--sku",
        default=None,
        help="SKU to dry-run (default: top SAFE_NATIONWIDE RESOLVED from snapshot)",
    )
    p_dry.add_argument("--snapshot-id", default="20260903_1744")
    p_dry.add_argument(
        "--no-ai-twin",
        action="store_true",
        help="Skip stub AI_ENHANCED creative twin",
    )
    p_dry.set_defaults(func=cmd_dry_run_sku)

    p_edf_in = sub.add_parser(
        "ebay-demand-ingest",
        help=(
            "Ingest provisional demand matches/signals JSON into EBAY_DEMAND_FIRST "
            "(scaffold; no live publish)"
        ),
    )
    p_edf_in.add_argument("--snapshot-id", required=True)
    p_edf_in.add_argument(
        "--signals-file",
        required=True,
        help="JSON file: {signals:[...]} / {matches:[...]} / bare list",
    )
    p_edf_in.set_defaults(func=cmd_ebay_demand_ingest)

    p_batch = sub.add_parser(
        "batch-creative-drafts",
        help=(
            "Batch-write optimized draft fields + ORIGINAL_SUPPLIER/AI_ENHANCED "
            "into SKU records and data/drafts/randmar_first/{safe_nationwide,"
            "destination_sensitive}/ (never publish)"
        ),
    )
    p_batch.add_argument("--snapshot-id", required=True)
    p_batch.add_argument(
        "--cohort",
        choices=["SAFE_NATIONWIDE", "DESTINATION_SENSITIVE"],
        default=None,
        help="Optional single cohort (default: both; SAFE_NATIONWIDE first)",
    )
    p_batch.add_argument("--limit", type=int, default=None, help="Optional SKU cap")
    p_batch.add_argument(
        "--no-ai-twin",
        action="store_true",
        help="Skip AI_ENHANCED creative twin files",
    )
    p_batch.set_defaults(func=cmd_batch_creative_drafts)


    p_ops = sub.add_parser(
        "ops-exceptions",
        help="Deterministic Ops exception engine (scan / list / rules)",
    )
    ops_sub = p_ops.add_subparsers(dest="ops_command", required=True)

    p_ops_scan = ops_sub.add_parser(
        "scan",
        help="Scan candidates/simulated listings; persist exceptions + pause",
    )
    p_ops_scan.add_argument("--snapshot-id", default=None)
    p_ops_scan.add_argument("--limit", type=int, default=None)
    p_ops_scan.add_argument(
        "--ingest-streak-threshold",
        type=int,
        default=3,
        help="Trailing ingest failure count that flags API_INGEST_FAILURE_STREAK",
    )
    p_ops_scan.add_argument(
        "--no-pause",
        action="store_true",
        help="Record exceptions without setting products.paused",
    )
    p_ops_scan.set_defaults(func=cmd_ops_exceptions)

    p_ops_list = ops_sub.add_parser(
        "list", help="List persisted ops_exceptions (newest first)"
    )
    p_ops_list.add_argument(
        "--status",
        default="open,paused",
        help="Comma-separated statuses (default: open,paused; use all for no filter)",
    )
    p_ops_list.add_argument("--rule", default=None, help="Filter by rule_code")
    p_ops_list.add_argument("--sku", default=None)
    p_ops_list.add_argument("--limit", type=int, default=100)
    p_ops_list.set_defaults(func=cmd_ops_exceptions)

    p_ops_rules = ops_sub.add_parser(
        "rules", help="Print deterministic exception rule catalog"
    )
    p_ops_rules.set_defaults(func=cmd_ops_exceptions)

    p_img = sub.add_parser(
        "backfill-images",
        help=(
            "Backfill SAFE_NATIONWIDE supplier stills via public read-only "
            "GET /Product/{sku}/Images + /Image/{id} (checkpointed; never GenerateImage)"
        ),
    )
    p_img.add_argument("--snapshot-id", default="20260903_1744")
    p_img.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional SKU cap for smoke tests",
    )
    p_img.add_argument(
        "--sleep",
        type=float,
        default=None,
        help="Seconds between API calls (default: SHIP_QUOTE_SLEEP_SEC)",
    )
    p_img.add_argument(
        "--no-resume",
        action="store_true",
        help="Ignore checkpoint and re-fetch all target SKUs",
    )
    p_img.add_argument(
        "--force",
        action="store_true",
        help="Re-fetch even when checkpoint marks SKU complete",
    )
    p_img.add_argument(
        "--urls-only",
        action="store_true",
        help="Skip binary Image/{id} downloads; list URLs only",
    )
    p_img.add_argument(
        "--use-token",
        action="store_true",
        help="Use OAuth bearer (default: public anonymous Product/Images)",
    )
    p_img.set_defaults(func=cmd_backfill_images)



    p_qa = sub.add_parser(
        "qa-ready",
        help=(
            "Automated QA for ready/listable SKUs (shipping p75, MAP/channel, "
            "UPC/MPN dupes, stock, margin floors, SAFE images, drafts). "
            "Never publish/order."
        ),
    )
    p_qa.add_argument(
        "--cohort",
        choices=["SAFE_NATIONWIDE", "DESTINATION_SENSITIVE", "QUARANTINE_UNRESOLVED"],
        default=None,
        help="Optional single cohort (default: SAFE_NATIONWIDE + DESTINATION_SENSITIVE)",
    )
    p_qa.add_argument(
        "--all-listable-cohorts",
        action="store_true",
        help="Include every cohort that currently has listable_pass=1",
    )
    p_qa.add_argument(
        "--include-non-listable",
        action="store_true",
        help="Also scan non-listable rows in selected cohorts",
    )
    p_qa.add_argument(
        "--no-write",
        action="store_true",
        help="Skip writing data/reports/ready_sku_qa_latest.{json,md}",
    )
    p_qa.add_argument(
        "--report-stem",
        default="ready_sku_qa_latest",
        help="Report filename stem under data/reports/",
    )
    p_qa.add_argument("--top", type=int, default=25, help="Top failing SKUs to list")
    p_qa.set_defaults(func=cmd_qa_ready)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

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
from firefinds.scoring.shipping import InjectedQuoteProvider


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

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

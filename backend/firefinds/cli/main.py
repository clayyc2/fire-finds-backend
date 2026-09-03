"""Fire Finds CLI: score | ingest-stub | ingest-live | rank."""

from __future__ import annotations

import argparse
import json
import sys

from firefinds.clients.randmar import SupplierOrdersDisabled
from firefinds.config import get_settings
from firefinds.services import (
    ingest_live,
    ingest_stub,
    rank_candidates,
    score_all,
)


def cmd_ingest_stub(_args: argparse.Namespace) -> int:
    settings = get_settings()
    count = ingest_stub(settings)
    print(f"ingest-stub: upserted {count} stub products into {settings.db_path}")
    return 0


def cmd_ingest_live(args: argparse.Namespace) -> int:
    """Read-only live catalog pull + score into SQLite."""
    settings = get_settings()
    if settings.supplier_orders_enabled is False:
        # Explicit refusal surface for any accidental order CLI wiring.
        pass
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
    """Refuse order placement when SUPPLIER_ORDERS_ENABLED is false."""
    settings = get_settings()
    if not settings.supplier_orders_enabled:
        print(
            "SUPPLIER_ORDERS_ENABLED is false; refusing to place order",
            file=sys.stderr,
        )
        return 2
    print("Live supplier orders are not implemented", file=sys.stderr)
    return 1


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

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

"""Fire Finds CLI: score | ingest-stub | rank."""

from __future__ import annotations

import argparse
import json
import sys

from firefinds.config import get_settings
from firefinds.services import ingest_stub, rank_candidates, score_all


def cmd_ingest_stub(_args: argparse.Namespace) -> int:
    settings = get_settings()
    count = ingest_stub(settings)
    print(f"ingest-stub: upserted {count} stub products into {settings.db_path}")
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

    p_score = sub.add_parser("score", help="Rescore all products in SQLite")
    p_score.set_defaults(func=cmd_score)

    p_rank = sub.add_parser("rank", help="Print top N passing candidates as JSON")
    p_rank.add_argument("-n", type=int, default=10, help="Number of candidates")
    p_rank.set_defaults(func=cmd_rank)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

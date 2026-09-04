#!/usr/bin/env python3
"""Run ready/listable SKU QA and write data/reports/ready_sku_qa_latest.{json,md}.

Gates stay OFF — never publish or place supplier orders.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from firefinds.cli.main import main  # noqa: E402


def main_script(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    return main(["qa-ready", *args])


if __name__ == "__main__":
    raise SystemExit(main_script())

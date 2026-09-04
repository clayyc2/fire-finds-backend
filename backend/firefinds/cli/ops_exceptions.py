"""Standalone `ops-exceptions` console entry (scan / list / rules)."""

from __future__ import annotations

import sys

from firefinds.cli.main import main


def main_ops(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    return main(["ops-exceptions", *args])


if __name__ == "__main__":
    raise SystemExit(main_ops())

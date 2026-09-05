"""Set starting prices for the complete eligible queue without any API calls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from firefinds.config import Settings
from firefinds.engine.starting_prices import price_queue
from firefinds.engine.storage import atomic_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", required=True, type=Path)
    parser.add_argument("--catalogue", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    # Never source .env. Explicit process environment is the Settings schema.
    result = price_queue(json.loads(args.queue.read_text()),
        json.loads(args.catalogue.read_text())["rows"], Settings.from_env())
    atomic_json(args.out, result)
    print(json.dumps({"priced": result["priced_count"], "published": 0,
        "first": [{"sku": row["sku"], **row["starting_price"]} for row in result["queue"][:5]]}, indent=2))


if __name__ == "__main__":
    main()

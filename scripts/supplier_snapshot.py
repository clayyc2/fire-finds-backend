"""Fetch current Randmar catalog privately; never quote carts or submit orders."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from firefinds.clients.randmar_readonly import ReadOnlyRandmarClient
from firefinds.engine.storage import atomic_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secrets-dir", type=Path, required=True)
    parser.add_argument("--reseller-id", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    client = ReadOnlyRandmarClient(args.secrets_dir, args.reseller_id)
    start = time.time()
    try:
        catalog = client.get_products_json()
        if not isinstance(catalog, list) or not catalog or any(not isinstance(r, dict) for r in catalog):
            raise ValueError("Unexpected catalog structure; do not guess")
        payload = {"source": "randmar.v4.report.products.json",
                   "reseller_id": args.reseller_id, "observed_at": start,
                   "received_at": time.time(), "rows": catalog}
        atomic_json(args.out, payload)
        print(json.dumps({"catalog_rows": len(catalog), "saved": True,
                          "observed_at": datetime.fromtimestamp(start, timezone.utc).isoformat(),
                          "sample_field_names": sorted(catalog[0]),
                          "supplier_orders_enabled": False}))
        return 0
    except Exception as exc:
        print(json.dumps({"saved": False, "error_type": type(exc).__name__,
                          "supplier_orders_enabled": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

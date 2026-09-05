"""Read current Product eligibility for mapped listings; never alters listings."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from firefinds.clients.randmar_readonly import ReadOnlyRandmarClient
from firefinds.engine.storage import atomic_json
from firefinds.fulfillment.supplier_product import parse_supplier_product


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--secrets-dir", type=Path, required=True)
    parser.add_argument("--reseller-id", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    mapping = json.loads(args.mapping.read_text())
    if not isinstance(mapping, dict) or not mapping or len(mapping) > 500:
        raise ValueError("Explicit bounded mapping required")
    skus = sorted(set(mapping.values()))
    if any(not isinstance(s, str) or not s for s in skus):
        raise ValueError("Invalid SKU mapping")
    client = ReadOnlyRandmarClient(args.secrets_dir, args.reseller_id)
    # Warm the authentication cache once before bounded parallel GETs.
    client.get_account()
    def inspect(sku):
        row = {"sku": sku, "observed_at": time.time(), "eligible_product": False}
        try:
            raw = client.get_product(sku)
            row.update(buyable=raw.get("AvailableToBuy"), opportunity_only=raw.get("OpportunityOnly"))
            product = parse_supplier_product(raw, sku)
            row.update(eligible_product=True, stock=product.stock,
                       cost=str(product.cost), map_price=str(product.map_price))
        except ValueError:
            row["reason"] = "product_gate_unresolved_or_restricted"
        except Exception as exc:
            row["reason"] = "read_failed:" + type(exc).__name__
        return row
    report = {"started_at": time.time(), "read_only": True, "rows": []}
    with ThreadPoolExecutor(max_workers=2) as pool:
        for row in pool.map(inspect, skus):
            report["rows"].append(row)
            atomic_json(args.out, report)
    report.update(completed_at=time.time(), checked=len(report["rows"]),
                  eligible_product_count=sum(r["eligible_product"] for r in report["rows"]))
    atomic_json(args.out, report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

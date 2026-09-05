"""Read existing eBay offers/inventory and compare an explicit Randmar snapshot."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from firefinds.clients.ebay_readonly import ReadOnlyEbayClient
from firefinds.fulfillment.identity import inspect_listing
from firefinds.engine.storage import atomic_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secrets-dir", required=True, type=Path)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--roster", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--stock-buffer", default=2, type=int)
    parser.add_argument("--from-snapshot", type=Path,
                        help="Recheck saved evidence offline; never refresh its observation time")
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_text())
    observed = catalog["observed_at"]
    if not args.from_snapshot and (not isinstance(observed, (int, float)) or not 0 <= time.time() - observed <= 3600):
        raise ValueError("Catalog must have been observed within one hour")
    by_sku = defaultdict(list)
    for row in catalog["rows"]:
        by_sku[row.get("RandmarSKU")].append(row)
    roster = json.loads(args.roster.read_text())["listingId_map"]
    if not isinstance(roster, dict) or not 1 <= len(roster) <= 500:
        raise ValueError("Bounded explicit roster required")
    client = None if args.from_snapshot else ReadOnlyEbayClient("production", args.secrets_dir)
    source = (json.loads(args.from_snapshot.read_text()) if args.from_snapshot else
              {"observed_at": time.time(), "catalog_observed_at": observed, "listings": []})
    if source.get("catalog_observed_at") != observed:
        raise ValueError("Snapshot belongs to a different catalog observation")
    saved = defaultdict(list)
    for row in source["listings"]:
        saved[(row["sku"], str(row["listing_id"]))].append(row)
    report = {"expected": len(roster), "complete": False, "checks": [], "writes_enabled": False}
    for sku, listing_id in roster.items():
        try:
            suppliers = by_sku[sku]
            if len(suppliers) != 1:
                raise ValueError("Supplier SKU absent or ambiguous")
            if args.from_snapshot:
                rows = saved[(sku, str(listing_id))]
                if len(rows) != 1:
                    raise ValueError("Snapshot listing absent or ambiguous")
                offers, inventory = rows[0]["offers"], rows[0]["inventory"]
            else:
                offers = client.get_offers_for_sku(sku)
                inventory = client.get_inventory_item(sku)
                source["listings"].append({"sku": sku, "listing_id": listing_id,
                                           "inventory": inventory, "offers": offers})
            report["checks"].append(inspect_listing(
                merchant_sku=sku, listing_id=listing_id, inventory=inventory,
                offers=offers, supplier=suppliers[0], stock_buffer=args.stock_buffer))
        except Exception as exc:
            report["checks"].append({"merchant_sku": sku, "listing_id": listing_id,
                                      "mapping_verified": False, "error_type": type(exc).__name__})
            if isinstance(exc, RuntimeError):
                break
        atomic_json(args.out / "ebay_inventory_source.json", source)
        atomic_json(args.out / "inventory_readiness.json", report)
    report["complete"] = len(report["checks"]) == len(roster)
    mapping = {r["merchant_sku"]: r["supplier_sku"] for r in report["checks"] if r.get("mapping_verified")}
    report["mapping_verified_count"] = len(mapping)
    report["observed_at"] = source["observed_at"]
    report["catalog_observed_at"] = observed
    report["evaluated_at"] = time.time()
    report["offline_recheck"] = bool(args.from_snapshot)
    report["hold_counts"] = dict(Counter(h for r in report["checks"] for h in r.get("observed_holds", [])))
    atomic_json(args.out / "inventory_readiness.json", report)
    atomic_json(args.out / "verified_sku_mapping.json", mapping)
    print(json.dumps({k: v for k, v in report.items() if k != "checks"}, indent=2))
    return 0 if report["complete"] and len(mapping) == len(roster) else 2


if __name__ == "__main__":
    raise SystemExit(main())

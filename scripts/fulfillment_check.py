"""One read-only fulfillment sweep; no .env, enable flags, purchases, or tracking POSTs."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from firefinds.clients.ebay_readonly import ReadOnlyEbayClient
from firefinds.clients.randmar_readonly import ReadOnlyRandmarClient
from firefinds.engine.services import Audit
from firefinds.fulfillment.worker import FulfillmentWorker
from firefinds.fulfillment.sweep import sweep_orders


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True, choices=["sandbox", "production"])
    parser.add_argument("--secrets-dir", required=True, type=Path)
    parser.add_argument("--reseller-id", required=True)
    parser.add_argument("--mapping", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    mapping = json.loads(args.mapping.read_text())
    if not isinstance(mapping, dict) or any(not isinstance(k, str) or not k.strip() or
            not isinstance(v, str) or not v.strip() for k, v in mapping.items()):
        raise ValueError("Explicit verified SKU mapping required")
    ebay = ReadOnlyEbayClient(args.environment, args.secrets_dir)
    supplier = ReadOnlyRandmarClient(args.secrets_dir, args.reseller_id)
    worker = FulfillmentWorker(settings=ebay.settings, ebay=ebay, supplier=supplier,
        audit=Audit(args.out / "audit.jsonl"), state_dir=args.out / "worker",
        sku_mapping=mapping, carrier_mapping={})
    report = sweep_orders(ebay=ebay, worker=worker, report_path=args.out / "order_check.json")
    print(json.dumps(dict(report, commerce_writes_enabled=False), indent=2))
    return 0 if report["complete"] and report["needs_attention"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())

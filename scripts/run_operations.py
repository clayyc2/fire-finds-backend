"""Scheduled catalogue pricing and order checks. No live-commerce switches."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from firefinds.clients.ebay_readonly import ReadOnlyEbayClient
from firefinds.clients.randmar_readonly import ReadOnlyRandmarClient
from firefinds.config import Settings
from firefinds.engine.services import Audit
from firefinds.fulfillment.worker import FulfillmentWorker
from firefinds.ops.runner import run_cycle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secrets-dir", required=True, type=Path)
    parser.add_argument("--mapping", required=True, type=Path)
    parser.add_argument("--purchase-audit", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--environment", choices=["sandbox", "production"], required=True)
    parser.add_argument("--reseller-id", required=True)
    args = parser.parse_args()
    os.umask(0o077)
    mapping = json.loads(args.mapping.read_text())
    if not isinstance(mapping, dict) or any(not isinstance(k, str) or not k.strip() or
            not isinstance(v, str) or not v.strip() for k, v in mapping.items()):
        raise ValueError("Explicit verified mapping required")
    denied = [r["sku"] for r in json.loads(args.purchase_audit.read_text())["rows"] if r.get("buyable") is False]
    ebay = ReadOnlyEbayClient(args.environment, args.secrets_dir)
    supplier = ReadOnlyRandmarClient(args.secrets_dir, args.reseller_id)
    worker = FulfillmentWorker(settings=ebay.settings, ebay=ebay, supplier=supplier,
        audit=Audit(args.out / "audit.jsonl"), state_dir=args.out / "worker",
        sku_mapping=mapping, carrier_mapping={})
    result = run_cycle(ebay=ebay, supplier=supplier, worker=worker, settings=Settings.from_env(),
        mapping=mapping, root=args.out, purchase_denied_skus=denied)
    print(json.dumps(result, indent=2))
    return 2 if result["needs_attention"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Inspect matched eBay accounts without loading .env or enabling writes."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from firefinds.clients.ebay_readonly import ReadOnlyEbayClient
from firefinds.engine.sandbox_ops import sanitized_read_report
from firefinds.engine.storage import atomic_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=["sandbox", "production"], required=True)
    parser.add_argument("--secrets-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--roster", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    args.out.mkdir(mode=0o700, parents=True, exist_ok=True)
    client = ReadOnlyEbayClient(args.environment, args.secrets_dir)
    report = sanitized_read_report(client, capacity_path=args.out / "capacity.json")
    report["observed_at"] = datetime.now(timezone.utc).isoformat()
    report["commerce_writes_allowed"] = False
    if args.roster:
        roster = json.loads(args.roster.read_text())
        mapping = roster["listingId_map"]
        if not isinstance(mapping, dict) or not 0 < len(mapping) <= 500:
            raise ValueError("Invalid bounded roster")
        checks = []
        for sku, listing_id in mapping.items():
            try:
                body = client.get_offers_for_sku(sku)
                offers = body.get("offers") or []
                matches = [o for o in offers if
                           str((o.get("listing") or {}).get("listingId")) == str(listing_id)]
                checks.append({"sku": sku, "listing_id": listing_id,
                               "matched": len(matches) == 1,
                               "published": len(matches) == 1 and matches[0].get("status") == "PUBLISHED"})
            except Exception as exc:
                checks.append({"sku": sku, "listing_id": listing_id, "matched": False,
                               "error_type": type(exc).__name__})
                # Do not spend a whole roster on failed auth/rate limits/network.
                if getattr(exc, "status", None) in (401, 403, 429) or isinstance(exc, RuntimeError):
                    break
        report["roster"] = {"expected": len(mapping), "checked": len(checks), "checks": checks,
                            "complete": len(checks) == len(mapping)}
    atomic_json(args.out / "account_readiness.json", report)
    print(json.dumps(report, indent=2))
    reads_ok = report.get("reads") and all(r.get("ok") for r in report["reads"].values())
    roster = report.get("roster")
    roster_ok = roster is None or (roster["complete"] and
                                  all(c.get("matched") and c.get("published") for c in roster["checks"]))
    return 0 if reads_ok and roster_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())

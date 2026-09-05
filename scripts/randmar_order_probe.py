#!/usr/bin/env python3
"""Authenticated Randmar probe that cannot submit an order."""
from __future__ import annotations

import argparse
import json

from firefinds.clients.randmar import RandmarClient
from firefinds.config import Settings
from firefinds.fulfillment.randmar_checkout import probe_order_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ebay-order-id", required=True)
    parser.add_argument("--sku", required=True)
    parser.add_argument("--name", default="Fire Finds Probe")
    parser.add_argument("--street1", required=True)
    parser.add_argument("--city", required=True)
    parser.add_argument("--province", required=True)
    parser.add_argument("--postal-code", required=True)
    parser.add_argument("--country", default="CA")
    parser.add_argument("--phone", required=True)
    args = parser.parse_args()
    settings = Settings()
    if settings.supplier_orders_enabled:
        raise SystemExit("Refusing probe: SUPPLIER_ORDERS_ENABLED must be false")
    result = probe_order_path(
        RandmarClient(settings), ebay_order_id=args.ebay_order_id, sku=args.sku,
        ship_to={"name": args.name, "street1": args.street1, "city": args.city,
                 "province": args.province, "postal_code": args.postal_code,
                 "country": args.country, "phone": args.phone},
    )
    # Schema names only: never print credentials or raw customer values.
    safe = {k: v for k, v in result.items() if k != "process_payload"}
    if "process_payload" in result:
        safe["process_payload_fields"] = sorted(result["process_payload"])
    print(json.dumps(safe, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

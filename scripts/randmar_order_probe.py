#!/usr/bin/env python3
"""Prove Randmar checkout up to — not including — ProcessNew.

Uses official OpenAPI V4 paths only. SUPPLIER_ORDERS stays off.
Never posts Cart/Process or Cart/ProcessNew.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from firefinds.clients.randmar import RandmarClient
from firefinds.config import get_settings
from firefinds.fulfillment.randmar_checkout import (
    PATH_CART_PROCESS_NEW,
    RandmarOrderProbe,
    probe_report_json,
)
from firefinds.fulfillment.randmar_reads import order_by_po


class ProbeClient:
    def __init__(self, inner: RandmarClient) -> None:
        self.inner = inner

    def cart_add_item_default(self, cart_name: str, sku: str, *, quantity: int = 1):
        return self.inner.cart_add_item_default(cart_name, sku, quantity=quantity)

    def cart_get(self, cart_name: str):
        return self.inner.cart_get(cart_name)

    def cart_delete(self, cart_name: str):
        return self.inner.cart_delete(cart_name)

    def cart_shipping_methods(self, cart_name: str, ship_to: dict):
        return self.inner.cart_shipping_methods(cart_name, ship_to)

    def order_by_po(self, po: str):
        return order_by_po(self.inner, po)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Randmar order probe (no Process)")
    p.add_argument("--ebay-order-id", required=True)
    p.add_argument("--sku", required=True)
    p.add_argument("--qty", type=int, default=1)
    p.add_argument("--name", default="Probe Buyer")
    p.add_argument("--street1", default="101 8 Ave SW")
    p.add_argument("--city", default="Calgary")
    p.add_argument("--province", default="AB")
    p.add_argument("--postal", default="T2P 1J9")
    p.add_argument("--country", default="CA")
    p.add_argument("--phone", default="4035550100")
    p.add_argument("--keep-cart", action="store_true")
    args = p.parse_args(argv)

    settings = get_settings()
    if settings.supplier_orders_enabled:
        print("SUPPLIER_ORDERS_ENABLED is on; probe refuses to run", file=sys.stderr)
        return 2
    inner = RandmarClient(settings)
    if not inner.credentials_present():
        print(
            json.dumps(
                {
                    "status": "CREDENTIALS_MISSING",
                    "official_submit_path": PATH_CART_PROCESS_NEW,
                    "process_called": False,
                    "note": "Need RANDMAR_CLIENT_ID + secret file to run live probe steps",
                },
                indent=2,
            )
        )
        return 3

    probe = RandmarOrderProbe(ProbeClient(inner), settings)
    report = probe.run(
        ebay_order_id=args.ebay_order_id,
        sku=args.sku,
        qty=args.qty,
        ship_to={
            "Name": args.name,
            "Street1": args.street1,
            "City": args.city,
            "Province": args.province,
            "PostalCode": args.postal,
            "Country": args.country,
            "ContactName": args.name,
            "ContactPhone": args.phone,
        },
        cleanup_cart=not args.keep_cart,
    )
    print(probe_report_json(report))
    return 0 if report.get("status") in {"PROBE_COMPLETE_NO_SUBMIT", "ALREADY_ORDERED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

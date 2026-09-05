"""Real supplier product/cart/quote check. Purchases are structurally unavailable."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from firefinds.clients.randmar_quote import QuoteOnlyRandmarClient
from firefinds.engine.storage import atomic_json
from firefinds.scoring.shipping import REPRESENTATIVE_DESTINATIONS
from firefinds.fulfillment.shipping_quote import parse_shipping_quotes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sku", required=True)
    parser.add_argument("--secrets-dir", required=True, type=Path)
    parser.add_argument("--reseller-id", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    cart_name = "ff-quote-" + uuid.uuid4().hex
    client = QuoteOnlyRandmarClient(args.secrets_dir, args.reseller_id, cart_names=[cart_name])
    report = {"sku": args.sku, "observed_at": time.time(), "cart_name": cart_name,
              "supplier_orders_enabled": False, "quotes": [], "cleanup": "not_needed"}
    touched = False
    try:
        product = client.get_product(args.sku)
        atomic_json(args.out / "product.json", product)
        report["buyable"] = isinstance(product, dict) and product.get("AvailableToBuy") is True
        if not report["buyable"] or product.get("OpportunityOnly") is not False:
            report["reason"] = "supplier_purchase_not_eligible"
            return 2
        touched = True
        client.cart_add_item_default(cart_name, args.sku, quantity=1)
        cart = client.cart_get(cart_name)
        atomic_json(args.out / "cart.json", cart)
        report["cart_fields"] = sorted(cart) if isinstance(cart, dict) else []
        report["cart_parts"] = [{"sku": p.get("RandmarSKU"), "buyable": p.get("AvailableToBuy"),
                                 "cart": p.get("Cart")} for p in (cart.get("PartNumbers") or [])]
        # These public screening addresses are never submitted as orders. Real
        # checkout must obtain a fresh quote for the actual buyer destination.
        for destination in REPRESENTATIVE_DESTINATIONS:
            ship_to = {"Name": "Fire Finds Estimate", "Street1": destination.street1, "Street2": "",
                       "City": destination.city, "Province": destination.province,
                       "PostalCode": destination.postal_code, "Country": destination.country}
            raw = client.cart_shipping_methods(cart_name, ship_to)
            atomic_json(args.out / (destination.dest_id + "-quote.json"), raw)
            methods = (raw.get("ShippingMethods") or {}).get("Methods") if isinstance(raw, dict) else None
            parsed = parse_shipping_quotes(raw)
            report["quotes"].append({"destination": destination.dest_id, "methods": methods,
                "cheapest_charge_upper_bound": str(parsed[0].charge_upper_bound),
                "delivery_promise_verified": False})
            atomic_json(args.out / "summary.json", report)
        report["reason"] = "quotes_observed_not_purchase_authorization"
        return 0
    except Exception as exc:
        report["error_type"] = type(exc).__name__
        return 2
    finally:
        if touched:
            try:
                client.cart_delete(cart_name)
                report["cleanup"] = "deleted_owned_quote_cart"
            except Exception as exc:
                report["cleanup"] = "failed:" + type(exc).__name__
        atomic_json(args.out / "summary.json", report)
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())

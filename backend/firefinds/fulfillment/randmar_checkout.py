"""Swagger-aligned Randmar checkout preparation and non-submitting probe."""
from __future__ import annotations

import re
import hashlib
from typing import Any, Mapping


PROCESS_FIELDS = {
    "Name", "Street1", "Street2", "City", "ProvinceCode", "PostalCode",
    "CountryCode", "PO", "CustomerPO", "Comment", "ShippingSlipComment",
    "ContactName", "ContactPhone", "ShippingMethodId", "AllowPartialShipment",
    "ShippingSlipFileB64", "FutureOrderDate", "OrderOnHold",
}


def cart_name_for(ebay_order_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", ebay_order_id).strip("-")
    if not safe:
        raise ValueError("eBay order id cannot produce an empty cart name")
    suffix = hashlib.sha256(ebay_order_id.encode()).hexdigest()[:20]
    return f"ff-ebay-{safe[:51]}-{suffix}"


def build_process_cart_input(
    ship_to: Mapping[str, Any], *, ebay_order_id: str,
    shipping_method_id: str, allow_partial_shipment: bool = True,
) -> dict[str, Any]:
    """Build only fields accepted by Randmar ProcessCartInput."""
    required = ("name", "street1", "city", "province", "postal_code", "country", "phone")
    missing = [name for name in required if not isinstance(ship_to.get(name), str) or not ship_to[name].strip()]
    if missing or not isinstance(shipping_method_id, str) or not shipping_method_id.strip() or not isinstance(ebay_order_id, str) or not ebay_order_id.strip():
        raise ValueError("missing checkout fields: " + ", ".join(missing or ["shipping_method_id/order_id"]))
    country = str(ship_to["country"]).strip().upper()
    province = str(ship_to["province"]).strip().upper()
    if country not in {"CA", "US"} or len(province) != 2:
        raise ValueError("Randmar requires CA/US and a two-letter province/state")
    name = str(ship_to["name"]).strip()
    return {
        "Name": name, "Street1": str(ship_to["street1"]).strip(),
        "Street2": str(ship_to.get("street2", "")).strip(),
        "City": str(ship_to["city"]).strip(), "ProvinceCode": province,
        "PostalCode": str(ship_to["postal_code"]).strip(), "CountryCode": country,
        "PO": str(ebay_order_id), "CustomerPO": str(ebay_order_id),
        "Comment": "", "ShippingSlipComment": "",
        "ContactName": name, "ContactPhone": str(ship_to["phone"]).strip(),
        "ShippingMethodId": str(shipping_method_id),
        "AllowPartialShipment": bool(allow_partial_shipment),
        "ShippingSlipFileB64": "", "FutureOrderDate": None, "OrderOnHold": False,
    }


def probe_order_path(client: Any, *, ebay_order_id: str, sku: str,
                     ship_to: Mapping[str, Any], quantity: int = 1) -> dict[str, Any]:
    """Exercise safe cart/quote/PO reads and return a held payload.

    Deliberately has no call to ``process_cart`` so this function cannot submit.
    """
    cart = cart_name_for(ebay_order_id)
    existing = client.get_order_by_po(ebay_order_id)
    if isinstance(existing, Mapping) and existing.get("OrderNumber"):
        return {"status": "duplicate", "order_number": existing["OrderNumber"]}
    client.cart_add_item_default(cart, sku, quantity=quantity)
    cart_state = client.cart_get(cart)
    shipping = client.cart_shipping_methods(cart, dict(ship_to))
    methods = (((shipping or {}).get("ShippingMethods") or {}).get("Methods") or [])
    if not methods or not methods[0].get("MethodId"):
        raise RuntimeError("Randmar returned no usable shipping method")
    payload = build_process_cart_input(
        ship_to, ebay_order_id=ebay_order_id,
        shipping_method_id=methods[0]["MethodId"],
    )
    return {"status": "held_before_submit", "cart_name": cart,
            "cart_schema": sorted(cart_state) if isinstance(cart_state, Mapping) else [],
            "shipping_method_fields": sorted(methods[0]), "process_payload": payload}

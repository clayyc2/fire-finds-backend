"""Randmar checkout path taken from official OpenAPI V4 — not invented names.

Spec: GET https://api.randmar.io/swagger/V4/swagger.json
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from firefinds.config import Settings

PATH_CART_ADD_DEFAULT = "/Cart/AddItem/{cartName}/{sku}/DefaultOpportunity"
PATH_CART_GET = "/Cart/{cartName}"
PATH_CART_DELETE = "/Cart/{cartName}"
PATH_CART_SHIPPING_METHODS = "/Cart/ShippingMethods/{cartName}"
PATH_CART_PROCESS_NEW = "/Cart/ProcessNew/{cartName}"  # IRREVERSIBLE
PATH_CART_PROCESS_LEGACY = "/Cart/Process/{cartName}"  # IRREVERSIBLE
PATH_ORDER_BY_PO = "/Order/PONumber/{resellerPONumber}"
PATH_ORDER_BY_NUMBER = "/Order/{orderNumber}"
PATH_ORDERS = "/Orders"
PATH_SHIPMENTS = "/Orders/Shipments"

IRREVERSIBLE = frozenset({PATH_CART_PROCESS_NEW, PATH_CART_PROCESS_LEGACY})

PROCESS_CART_INPUT_FIELDS = (
    "Name",
    "Street1",
    "Street2",
    "City",
    "ProvinceCode",
    "PostalCode",
    "CountryCode",
    "PO",
    "CustomerPO",
    "Comment",
    "ShippingSlipComment",
    "ContactName",
    "ContactPhone",
    "ShippingMethodId",
    "AllowPartialShipment",
    "ShippingSlipFileB64",
    "FutureOrderDate",
    "OrderOnHold",
)

_SAFE_CART = re.compile(r"[^A-Za-z0-9._-]+")


def cart_name_for_ebay_order(ebay_order_id: str) -> str:
    raw = _SAFE_CART.sub("-", str(ebay_order_id).strip()) or "unknown"
    return f"ff-ebay-{raw}"[:80]


def po_for_ebay_order(ebay_order_id: str) -> str:
    return str(ebay_order_id).strip()


def process_cart_input(
    *,
    name: str,
    street1: str,
    city: str,
    province_code: str,
    postal_code: str,
    country_code: str,
    po: str,
    contact_name: str,
    contact_phone: str,
    shipping_method_id: str,
    street2: str = "",
    customer_po: str = "",
    comment: str = "",
    shipping_slip_comment: str = "",
    allow_partial_shipment: bool = True,
) -> dict[str, Any]:
    """Build ProcessCartInput. Official rule: no null strings."""
    cc = country_code.strip().upper()
    if cc not in {"CA", "US"}:
        raise ValueError("CountryCode must be CA or US")
    pc = province_code.strip().upper()
    if len(pc) != 2:
        raise ValueError("ProvinceCode must be two letters")
    if not contact_name.strip() or not contact_phone.strip():
        raise ValueError("ContactName and ContactPhone are required")
    if not shipping_method_id.strip():
        raise ValueError("ShippingMethodId required from Cart/ShippingMethods")
    return {
        "Name": name.strip(),
        "Street1": street1.strip(),
        "Street2": street2 or "",
        "City": city.strip(),
        "ProvinceCode": pc,
        "PostalCode": postal_code.strip(),
        "CountryCode": cc,
        "PO": po.strip(),
        "CustomerPO": customer_po or "",
        "Comment": comment or "",
        "ShippingSlipComment": shipping_slip_comment or "",
        "ContactName": contact_name.strip(),
        "ContactPhone": contact_phone.strip(),
        "ShippingMethodId": shipping_method_id.strip(),
        "AllowPartialShipment": bool(allow_partial_shipment),
        "ShippingSlipFileB64": "",
        "FutureOrderDate": None,
        "OrderOnHold": False,
    }


def sanitize_for_log(obj: Any) -> Any:
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            lk = str(k).lower()
            if lk in {"authorization", "client_secret", "access_token", "refresh_token", "password"}:
                out[k] = "[redacted]"
            else:
                out[k] = sanitize_for_log(v)
        return out
    if isinstance(obj, list):
        return [sanitize_for_log(x) for x in obj]
    return obj


def pick_shipping_method_id(payload: Any) -> str | None:
    methods: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        info = payload.get("ShippingMethods") or payload
        if isinstance(info, dict) and isinstance(info.get("Methods"), list):
            methods = [m for m in info["Methods"] if isinstance(m, dict)]
        elif isinstance(payload.get("Methods"), list):
            methods = [m for m in payload["Methods"] if isinstance(m, dict)]
    elif isinstance(payload, list):
        methods = [m for m in payload if isinstance(m, dict)]
    for m in methods:
        mid = m.get("MethodId")
        if mid:
            return str(mid)
    return None


@dataclass
class ProbeStep:
    name: str
    method: str
    path: str
    called: bool
    irreversible: bool
    request_keys: list[str] = field(default_factory=list)
    response_keys: list[str] = field(default_factory=list)
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "method": self.method,
            "path": self.path,
            "called": self.called,
            "irreversible": self.irreversible,
            "request_keys": self.request_keys,
            "response_keys": self.response_keys,
            "note": self.note,
        }


def _keys(obj: Any) -> list[str]:
    if isinstance(obj, dict):
        return sorted(obj.keys())
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        return sorted(obj[0].keys())
    return []


class RandmarOrderProbe:
    """Runs every step except Process / ProcessNew."""

    def __init__(self, client: Any, settings: Settings) -> None:
        self.client = client
        self.settings = settings
        self.steps: list[ProbeStep] = []

    def run(
        self,
        *,
        ebay_order_id: str,
        sku: str,
        qty: int,
        ship_to: dict[str, str],
        cleanup_cart: bool = True,
    ) -> dict[str, Any]:
        cart = cart_name_for_ebay_order(ebay_order_id)
        po = po_for_ebay_order(ebay_order_id)
        notes: list[str] = []

        existing = None
        try:
            existing = self.client.order_by_po(po)
            self.steps.append(
                ProbeStep(
                    "idempotency_po_lookup",
                    "GET",
                    PATH_ORDER_BY_PO,
                    True,
                    False,
                    response_keys=_keys(existing),
                    note="if this returns an order, do not ProcessNew",
                )
            )
        except Exception as exc:  # noqa: BLE001
            self.steps.append(
                ProbeStep(
                    "idempotency_po_lookup",
                    "GET",
                    PATH_ORDER_BY_PO,
                    True,
                    False,
                    note=f"lookup_error:{type(exc).__name__}",
                )
            )
        if isinstance(existing, dict) and (existing.get("OrderNumber") or existing.get("orderNumber")):
            return {
                "status": "ALREADY_ORDERED",
                "ebay_order_id": ebay_order_id,
                "po": po,
                "randmar_order_number": existing.get("OrderNumber") or existing.get("orderNumber"),
                "process_called": False,
                "steps": [s.as_dict() for s in self.steps],
            }

        add = self.client.cart_add_item_default(cart, sku, quantity=qty)
        self.steps.append(
            ProbeStep("add_item", "POST", PATH_CART_ADD_DEFAULT, True, False, response_keys=_keys(add))
        )
        cart_body = self.client.cart_get(cart)
        self.steps.append(
            ProbeStep("get_cart", "GET", PATH_CART_GET, True, False, response_keys=_keys(cart_body))
        )
        ship_payload = {
            "ShipTo": {
                "Name": ship_to.get("Name") or ship_to.get("name") or "",
                "Street1": ship_to.get("Street1") or ship_to.get("street1") or "",
                "Street2": ship_to.get("Street2") or ship_to.get("street2") or "",
                "City": ship_to.get("City") or ship_to.get("city") or "",
                "Province": ship_to.get("Province") or ship_to.get("province") or "",
                "PostalCode": ship_to.get("PostalCode") or ship_to.get("postal") or "",
                "Country": ship_to.get("Country") or ship_to.get("country") or "CA",
            }
        }
        methods = self.client.cart_shipping_methods(cart, ship_payload["ShipTo"])
        method_id = pick_shipping_method_id(methods)
        self.steps.append(
            ProbeStep(
                "shipping_methods",
                "POST",
                PATH_CART_SHIPPING_METHODS,
                True,
                False,
                request_keys=["ShipTo"],
                response_keys=_keys(methods),
                note=f"method_id={method_id}",
            )
        )
        prepared = None
        if method_id:
            prepared = process_cart_input(
                name=ship_payload["ShipTo"]["Name"] or "eBay Buyer",
                street1=ship_payload["ShipTo"]["Street1"],
                street2=ship_payload["ShipTo"]["Street2"],
                city=ship_payload["ShipTo"]["City"],
                province_code=ship_payload["ShipTo"]["Province"],
                postal_code=ship_payload["ShipTo"]["PostalCode"],
                country_code=ship_payload["ShipTo"]["Country"] or "CA",
                po=po,
                contact_name=ship_to.get("ContactName") or ship_payload["ShipTo"]["Name"] or "eBay Buyer",
                contact_phone=ship_to.get("ContactPhone") or "0000000000",
                shipping_method_id=method_id,
            )
            notes.append("ProcessCartInput prepared; ProcessNew NOT sent")
        else:
            notes.append("no ShippingMethodId — cannot prepare ProcessCartInput")

        self.steps.append(
            ProbeStep(
                "process_new_held",
                "POST",
                PATH_CART_PROCESS_NEW,
                False,
                True,
                request_keys=list(PROCESS_CART_INPUT_FIELDS),
                note="SUPPLIER_ORDERS off; irreversible call skipped",
            )
        )
        if cleanup_cart:
            try:
                self.client.cart_delete(cart)
                self.steps.append(ProbeStep("delete_cart", "DELETE", PATH_CART_DELETE, True, False))
            except Exception as exc:  # noqa: BLE001
                notes.append(f"cart_delete:{type(exc).__name__}")

        return {
            "status": "PROBE_COMPLETE_NO_SUBMIT",
            "ebay_order_id": ebay_order_id,
            "po": po,
            "cart_name": cart,
            "sku": sku,
            "qty": qty,
            "shipping_method_id": method_id,
            "process_cart_input": sanitize_for_log(prepared) if prepared else None,
            "process_called": False,
            "supplier_orders_enabled": bool(self.settings.supplier_orders_enabled),
            "notes": notes,
            "steps": [s.as_dict() for s in self.steps],
            "official_submit_path": PATH_CART_PROCESS_NEW,
        }


def probe_report_json(report: dict[str, Any]) -> str:
    return json.dumps(sanitize_for_log(report), indent=2, default=str)

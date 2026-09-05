"""eBay paid-order ingest. Submit stays refused.

States: SEEN -> MAPPED -> ROUTED_OFF
Idempotency key = eBay orderId (also Randmar ProcessCartInput.PO).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

from firefinds.config import Settings
from firefinds.engine.services import Audit
from .storage import atomic_json, checkpoint_lock

SEEN = "SEEN"
MAPPED = "MAPPED"
ROUTED_OFF = "ROUTED_OFF"
BLOCKED = "BLOCKED"

TERMINAL = frozenset({ROUTED_OFF})


@dataclass
class IngestRecord:
    ebay_order_id: str
    state: str
    sku: str | None = None
    qty: int = 0
    ship_to: dict[str, str] = field(default_factory=dict)
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def as_audit_dict(self) -> dict[str, Any]:
        """Return operational metadata without buyer personally identifying data."""
        return {
            "ebay_order_id": self.ebay_order_id,
            "state": self.state,
            "sku": self.sku,
            "qty": self.qty,
            "reason": self.reason,
            "ship_to_present": any(bool(v) for v in self.ship_to.values()),
            "ship_to_fields_present": sorted(k for k, v in self.ship_to.items() if v),
        }


def map_ebay_order(order: Mapping[str, Any]) -> IngestRecord:
    oid = str(order.get("orderId") or order.get("order_id") or "").strip()
    if not oid:
        return IngestRecord("", BLOCKED, reason="missing_order_id")
    if order.get("orderPaymentStatus") != "PAID":
        return IngestRecord(oid, BLOCKED, reason="payment_not_confirmed")
    cancel = order.get("cancelStatus") or {}
    if not isinstance(cancel, dict) or cancel.get("cancelState", "NONE_REQUESTED") != "NONE_REQUESTED":
        return IngestRecord(oid, BLOCKED, reason="cancellation_pending_or_complete")
    if order.get("orderFulfillmentStatus") != "NOT_STARTED":
        return IngestRecord(oid, BLOCKED, reason="fulfillment_not_new")
    items = order.get("lineItems") or order.get("line_items") or []
    if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
        return IngestRecord(oid, BLOCKED, reason="single_line_order_required")
    line = items[0]
    # A listing ID/line-item ID is never a Randmar SKU.
    sku = str(line.get("sku") or "").strip() or None
    qty = line.get("quantity")
    if type(qty) is not int or qty <= 0:
        return IngestRecord(oid, BLOCKED, reason="invalid_quantity")
    ship = order.get("shippingAddress") or order.get("fulfillmentStartInstructions") or {}
    if isinstance(ship, list) and ship:
        ship = (ship[0] or {}).get("shippingStep", {}).get("shipTo", {}) if isinstance(ship[0], dict) else {}
    if not isinstance(ship, dict):
        ship = {}
    contact = ship.get("contactAddress") if isinstance(ship.get("contactAddress"), dict) else ship
    ship_to = {
        "Name": str(ship.get("fullName") or contact.get("fullName") or ""),
        "Street1": str(contact.get("addressLine1") or contact.get("Street1") or ""),
        "Street2": str(contact.get("addressLine2") or ""),
        "City": str(contact.get("city") or ""),
        "Province": str(contact.get("stateOrProvince") or contact.get("Province") or ""),
        "PostalCode": str(contact.get("postalCode") or ""),
        "Country": str(contact.get("countryCode") or ""),
        "ContactPhone": str((ship.get("primaryPhone", {}).get("phoneNumber") or "") if isinstance(ship.get("primaryPhone"), dict) else ""),
    }
    if not sku:
        return IngestRecord(oid, BLOCKED, reason="unmapped_sku", ship_to=ship_to)
    if any(not ship_to[field].strip() for field in
           ("Name", "Street1", "City", "Province", "PostalCode", "Country")):
        return IngestRecord(oid, BLOCKED, reason="incomplete_shipping_address", sku=sku, qty=qty)
    return IngestRecord(oid, MAPPED, sku=sku, qty=qty, ship_to=ship_to)


class OrderIngest:
    def __init__(self, settings: Settings, audit: Audit, store: Path) -> None:
        self.settings = settings
        self.audit = audit
        self.store = store
        self.records: dict[str, IngestRecord] = self._load()

    def _load(self) -> dict[str, IngestRecord]:
        if not self.store.is_file():
            return {}
        raw = json.loads(self.store.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("invalid order ingest checkpoint")
        out: dict[str, IngestRecord] = {}
        if isinstance(raw, dict):
            for k, v in raw.items():
                if isinstance(v, dict) and v.get("ebay_order_id"):
                    out[k] = IngestRecord(**{f: v.get(f) for f in IngestRecord.__dataclass_fields__})
        return out

    def _save(self) -> None:
        self.store.parent.mkdir(parents=True, exist_ok=True)
        payload = {k: r.as_dict() for k, r in self.records.items()}
        atomic_json(self.store, payload)

    def ingest(self, order: Mapping[str, Any]) -> IngestRecord:
        with checkpoint_lock(self.store):
            self.records = self._load()
            return self._ingest_locked(order)

    def _ingest_locked(self, order: Mapping[str, Any]) -> IngestRecord:
        oid = str(order.get("orderId") or order.get("order_id") or "").strip()
        if not oid:
            rec = IngestRecord("", BLOCKED, reason="missing_order_id")
            self.audit.write("order_ingest_blocked", rec.as_audit_dict())
            return rec
        existing = self.records.get(oid)
        if existing and existing.state in TERMINAL:
            self.audit.write("order_ingest_replay", existing.as_audit_dict())
            return existing
        rec = IngestRecord(oid, SEEN)
        self.audit.write("order_ingest_seen", rec.as_audit_dict())
        mapped = map_ebay_order(order)
        if mapped.state == BLOCKED:
            self.records[oid] = mapped
            self._save()
            self.audit.write("order_ingest_blocked", mapped.as_audit_dict())
            return mapped
        rec = mapped
        rec.state = MAPPED
        self.audit.write("order_ingest_mapped", rec.as_audit_dict())
        rec.state = ROUTED_OFF
        rec.reason = "supplier_orders_disabled"
        if self.settings.supplier_orders_enabled and not self.settings.dry_run and not self.settings.global_kill_switch:
            rec.reason = "submit_refused_by_router_policy"
        self.records[oid] = rec
        self._save()
        self.audit.write("order_ingest_routed_off", rec.as_audit_dict())
        return rec


def dry_run_lifecycle(settings: Settings, audit: Audit, store: Path, order: Mapping[str, Any]) -> dict[str, Any]:
    ingest = OrderIngest(settings, audit, store)
    rec = ingest.ingest(order)
    return {
        "state": rec.state,
        "ebay_order_id": rec.ebay_order_id,
        "sku": rec.sku,
        "qty": rec.qty,
        "process_called": False,
        "tracking_posted": False,
        "publish_called": False,
        "reason": rec.reason,
        "replay": ingest.ingest(order).state == rec.state,
    }

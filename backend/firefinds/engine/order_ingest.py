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

SEEN = "SEEN"
MAPPED = "MAPPED"
ROUTED_OFF = "ROUTED_OFF"
BLOCKED = "BLOCKED"

TERMINAL = frozenset({ROUTED_OFF, BLOCKED})


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


def map_ebay_order(order: Mapping[str, Any]) -> IngestRecord:
    oid = str(order.get("orderId") or order.get("order_id") or "").strip()
    if not oid:
        return IngestRecord("", BLOCKED, reason="missing_order_id")
    line = None
    items = order.get("lineItems") or order.get("line_items") or []
    if isinstance(items, list) and items and isinstance(items[0], dict):
        line = items[0]
    sku = None
    qty = 1
    if line:
        sku = str(line.get("sku") or line.get("legacyItemId") or line.get("lineItemId") or "") or None
        try:
            qty = int(line.get("quantity") or 1)
        except (TypeError, ValueError):
            qty = 1
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
        "Country": str(contact.get("countryCode") or "CA"),
        "ContactPhone": str(ship.get("primaryPhone", {}).get("phoneNumber") if isinstance(ship.get("primaryPhone"), dict) else ""),
    }
    if not sku:
        return IngestRecord(oid, BLOCKED, reason="unmapped_sku", ship_to=ship_to)
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
        try:
            raw = json.loads(self.store.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        out: dict[str, IngestRecord] = {}
        if isinstance(raw, dict):
            for k, v in raw.items():
                if isinstance(v, dict) and v.get("ebay_order_id"):
                    out[k] = IngestRecord(**{f: v.get(f) for f in IngestRecord.__dataclass_fields__})
        return out

    def _save(self) -> None:
        self.store.parent.mkdir(parents=True, exist_ok=True)
        payload = {k: r.as_dict() for k, r in self.records.items()}
        tmp = self.store.with_suffix(self.store.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.store)

    def ingest(self, order: Mapping[str, Any]) -> IngestRecord:
        oid = str(order.get("orderId") or order.get("order_id") or "").strip()
        if not oid:
            rec = IngestRecord("", BLOCKED, reason="missing_order_id")
            self.audit.write("order_ingest_blocked", rec.as_dict())
            return rec
        existing = self.records.get(oid)
        if existing and existing.state in TERMINAL:
            self.audit.write("order_ingest_replay", existing.as_dict())
            return existing
        rec = IngestRecord(oid, SEEN)
        self.audit.write("order_ingest_seen", rec.as_dict())
        mapped = map_ebay_order(order)
        if mapped.state == BLOCKED:
            self.records[oid] = mapped
            self._save()
            self.audit.write("order_ingest_blocked", mapped.as_dict())
            return mapped
        rec = mapped
        rec.state = MAPPED
        self.audit.write("order_ingest_mapped", rec.as_dict())
        rec.state = ROUTED_OFF
        rec.reason = "supplier_orders_disabled"
        if self.settings.supplier_orders_enabled and not self.settings.dry_run and not self.settings.global_kill_switch:
            rec.reason = "submit_refused_by_router_policy"
        self.records[oid] = rec
        self._save()
        self.audit.write("order_ingest_routed_off", rec.as_dict())
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

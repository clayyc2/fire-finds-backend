"""Durable tracking intent and GET reconciliation; never blindly retry a POST."""
from __future__ import annotations

import hashlib
import json

from firefinds.engine.storage import atomic_json, checkpoint_lock


def same_shipment(row, payload):
    if not isinstance(row, dict):
        return False
    return all(row.get(k) == payload[k] for k in ("shippingCarrierCode", "trackingNumber", "lineItems"))


class TrackingDelivery:
    def __init__(self, settings, audit, checkpoint):
        self.s, self.audit, self.path = settings, audit, checkpoint

    def deliver(self, order_id, payload, ebay):
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        with checkpoint_lock(self.path):
            ledger = json.loads(self.path.read_text()) if self.path.is_file() else {}
            if not isinstance(ledger, dict) or any(not isinstance(r, dict) or r.get("state") not in
                    {"POSTING", "UNKNOWN", "CONFIRMED"} for r in ledger.values()):
                raise ValueError("Invalid tracking checkpoint; recovery required")
            previous = ledger.get(order_id)
            if previous and previous.get("digest") != digest:
                return "tracking_payload_changed"
            if previous and previous["state"] == "CONFIRMED":
                return "confirmed"
            # Even an apparently successful POST requires GET evidence before
            # completion. Unknown/partial list responses cannot authorize retry.
            evidence = ebay.list_shipping_fulfillments(order_id)
            rows = evidence.get("fulfillments") if isinstance(evidence, dict) else None
            if not isinstance(rows, list):
                return "tracking_read_unresolved"
            if any(same_shipment(row, payload) for row in rows):
                ledger[order_id] = {"state": "CONFIRMED", "digest": digest}
                atomic_json(self.path, ledger)
                self.audit.write("tracking_confirmed", {"order_id": order_id})
                return "confirmed"
            if previous:
                return "tracking_reconciliation_required"
            if rows:
                return "existing_tracking_conflict"
            if (self.s.dry_run or self.s.global_kill_switch or not self.s.ebay_tracking_updates_enabled
                    or (self.s.ebay_env == "production" and
                        (not self.s.ebay_production_enabled or not self.s.live_listings_enabled))):
                return "tracking_updates_disabled"
            ledger[order_id] = {"state": "POSTING", "digest": digest}
            atomic_json(self.path, ledger)
            self.audit.write("tracking_post_intent", {"order_id": order_id})
            try:
                ebay.create_shipping_fulfillment(order_id, carrier_code=payload["shippingCarrierCode"],
                                                 tracking_number=payload["trackingNumber"],
                                                 line_items=payload["lineItems"])
            except Exception:
                ledger[order_id]["state"] = "UNKNOWN"
                atomic_json(self.path, ledger)
                self.audit.write("tracking_outcome_unknown", {"order_id": order_id})
                return "tracking_reconciliation_required"
            # Persisted intent survives a crash before the next read. A later
            # pass reconciles it; it never sends the same POST a second time.
            self.audit.write("tracking_post_returned", {"order_id": order_id})
            return "tracking_confirmation_pending"

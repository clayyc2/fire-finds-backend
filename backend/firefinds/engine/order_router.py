"""Durable at-most-once submission guard, not a production fulfillment worker.

A timeout can mean a supplier accepted a purchase. Never retry a submission:
persist SUBMITTING first, and hold unknown outcomes for PO reconciliation.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from .storage import atomic_json, checkpoint_lock


class OrderRouter:
    def __init__(self, settings, audit, checkpoint: Path | None = None):
        self.s = settings
        self.audit = audit
        self.checkpoint = checkpoint

    def _load(self):
        if not self.checkpoint.is_file():
            return {}
        # Invalid/unreadable state must never be treated as an empty ledger.
        raw = json.loads(self.checkpoint.read_text(encoding="utf-8"))
        if isinstance(raw, list) and all(isinstance(key, str) for key in raw):
            return {key: {"state": "SUBMITTED"} for key in raw}
        if not isinstance(raw, dict) or any(
            not isinstance(row, dict) or row.get("state") not in
            {"SUBMITTING", "UNKNOWN", "SUBMITTED"} for row in raw.values()
        ):
            raise ValueError("invalid order submission checkpoint; recovery required")
        return raw

    def _finish(self, key, state, supplier_order_number=None):
        with checkpoint_lock(self.checkpoint):
            rows = self._load()
            rows[key] = {"state": state}
            if supplier_order_number:
                rows[key]["supplier_order_number"] = supplier_order_number
            atomic_json(self.checkpoint, rows)

    def route(self, order: Mapping[str, Any], submit: Callable) -> str:
        key = str(order.get("order_id") or "").strip()
        if not key:
            raise ValueError("order_id is required")
        if self.s.dry_run or self.s.global_kill_switch or not self.s.supplier_orders_enabled:
            self.audit.write("order_dry_run", {"order_id": key})
            return "dry-run"
        if self.checkpoint is None:
            raise ValueError("durable checkpoint required for supplier submission")
        with checkpoint_lock(self.checkpoint):
            rows = self._load()
            if key in rows:
                state = rows[key]["state"]
                result = "duplicate" if state == "SUBMITTED" else "reconciliation-required"
                self.audit.write("order_replay", {"order_id": key, "state": state})
                return result
            rows[key] = {"state": "SUBMITTING"}
            atomic_json(self.checkpoint, rows)
        self.audit.write("order_submit_intent", {"order_id": key})
        try:
            result = submit(order)  # Deliberately a single attempt.
            number = result.get("OrderNumber") if isinstance(result, Mapping) else result
            if not isinstance(number, str) or not number.strip():
                raise ValueError("supplier confirmation missing")
        except Exception:
            self._finish(key, "UNKNOWN")
            self.audit.write("order_outcome_unknown", {"order_id": key})
            raise
        self._finish(key, "SUBMITTED", number.strip())
        self.audit.write("order_submitted", {"order_id": key})
        return str(result)

    def reconcile(self, order_id: str, lookup_by_po: Callable) -> str:
        """Read supplier PO evidence; never release an uncertain order for retry."""
        if self.checkpoint is None:
            raise ValueError("durable checkpoint required")
        with checkpoint_lock(self.checkpoint):
            rows = self._load()
            if order_id not in rows:
                raise ValueError("order not in submission ledger")
            if rows[order_id]["state"] == "SUBMITTED":
                return "duplicate"
            evidence = lookup_by_po(order_id)
            if (not isinstance(evidence, Mapping) or evidence.get("PONumber") != order_id
                    or not isinstance(evidence.get("OrderNumber"), str)
                    or not evidence["OrderNumber"].strip()):
                return "reconciliation-required"
            rows[order_id] = {"state": "SUBMITTED", "supplier_order_number": evidence["OrderNumber"]}
            atomic_json(self.checkpoint, rows)
        self.audit.write("order_reconciled", {"order_id": order_id})
        return "reconciled"

"""Shared durable supplier-cash reservations; no AI in the authorization path."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal as D, ROUND_CEILING
import json
from zoneinfo import ZoneInfo

from firefinds.engine.storage import atomic_json, checkpoint_lock


class DailySupplierBudget:
    def __init__(self, settings, checkpoint, clock):
        self.limit = D(str(settings.daily_supplier_spend_limit_cad))
        if not self.limit.is_finite() or self.limit < 0:
            raise ValueError("Invalid daily supplier spend limit")
        self.zone = ZoneInfo(settings.supplier_spend_timezone)
        self.path, self.clock = checkpoint, clock

    def _day(self):
        return datetime.fromtimestamp(self.clock(), self.zone).date().isoformat()

    def _load(self):
        rows = json.loads(self.path.read_text()) if self.path.is_file() else {}
        if not isinstance(rows, dict):
            raise ValueError("Invalid spend ledger; recovery required")
        for oid, row in rows.items():
            if (not isinstance(oid, str) or not oid or not isinstance(row, dict) or
                    row.get("state") not in {"RESERVED", "SPENT"} or
                    not isinstance(row.get("days"), list) or not row["days"]):
                raise ValueError("Invalid spend record; recovery required")
            amount = D(row["amount_cad"])
            if not amount.is_finite() or amount <= 0:
                raise ValueError("Invalid spend amount")
            for day in row["days"]:
                if datetime.strptime(day, "%Y-%m-%d").date().isoformat() != day:
                    raise ValueError("Invalid spend date")
        return rows

    def execute(self, order_id, amount_cad, operation):
        """Reserve BEFORE the durable router/HTTP call; never retry an uncertain
        reservation. Hold the shared lock through dispatch so parallel workers
        cannot authorize more than the configured cash limit.
        """
        amount = D(str(amount_cad))
        if not isinstance(order_id, str) or not order_id or not amount.is_finite() or amount <= 0:
            raise ValueError("Explicit order and positive cash upper bound required")
        amount = amount.quantize(D("0.01"), rounding=ROUND_CEILING)
        with checkpoint_lock(self.path):
            rows, day = self._load(), self._day()
            if order_id in rows:
                return {"allowed": False, "reason": "supplier_spend_reservation_requires_reconciliation"}
            used = sum((D(row["amount_cad"]) for row in rows.values()
                        if row["state"] == "RESERVED" or day in row["days"]), D(0))
            if used + amount > self.limit:
                return {"allowed": False, "reason": "daily_supplier_spend_limit"}
            rows[order_id] = {"state": "RESERVED", "amount_cad": str(amount), "days": [day]}
            atomic_json(self.path, rows)
            # Exceptions/termination deliberately leave the reservation intact,
            # including on later days, until positive reconciliation.
            result = operation()
            rows[order_id]["state"] = "SPENT"
            rows[order_id]["days"] = sorted({day, self._day()})
            atomic_json(self.path, rows)
            return {"allowed": True, "result": result}

    def confirm(self, order_id):
        """Positive PO evidence resolves uncertainty; no budget is refunded.
        Cross-day reconciliation conservatively consumes both dates' allowance.
        """
        with checkpoint_lock(self.path):
            rows = self._load()
            if order_id not in rows:
                raise ValueError("Missing supplier cash reservation")
            if rows[order_id]["state"] == "RESERVED":
                rows[order_id]["state"] = "SPENT"
                rows[order_id]["days"] = sorted(set(rows[order_id]["days"] + [self._day()]))
                atomic_json(self.path, rows)

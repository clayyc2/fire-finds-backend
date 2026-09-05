"""Apply official Account API privilege reads to Capacity Manager.

Never invent selling limits. Missing/unreadable privilege => no live cap.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal as D
from typing import Any, Mapping


@dataclass(frozen=True)
class SellingLimitSnapshot:
    source: str
    seller_registration_completed: bool | None
    quantity: int | None
    amount_cad: D | None
    raw_keys: tuple[str, ...] = ()

    @property
    def has_live_cap(self) -> bool:
        return self.quantity is not None or self.amount_cad is not None


def parse_privilege_payload(payload: Mapping[str, Any] | None) -> SellingLimitSnapshot:
    if not isinstance(payload, dict) or not payload:
        return SellingLimitSnapshot("missing", None, None, None)
    limit = payload.get("sellingLimit") or payload.get("selling_limit") or {}
    if not isinstance(limit, dict):
        limit = {}
    qty = limit.get("quantity")
    try:
        qty_i = int(qty) if qty is not None else None
    except (TypeError, ValueError):
        qty_i = None
    amount = limit.get("amount") if isinstance(limit.get("amount"), dict) else {}
    value = amount.get("value") if isinstance(amount, dict) else None
    try:
        amt = D(str(value)) if value is not None else None
    except Exception:
        amt = None
    completed = payload.get("sellerRegistrationCompleted")
    if completed is None:
        completed = payload.get("seller_registration_completed")
    if completed is not None:
        completed = bool(completed)
    return SellingLimitSnapshot(
        source="sell.account.v1.privilege",
        seller_registration_completed=completed,
        quantity=qty_i,
        amount_cad=amt,
        raw_keys=tuple(sorted(payload.keys())),
    )


def apply_live_caps(
    *,
    configured_item_limit: int,
    configured_value_limit_cad: float,
    snapshot: SellingLimitSnapshot,
) -> tuple[int, float]:
    """Intersect configured caps with live privilege. None live field = unused."""
    item = configured_item_limit
    value = configured_value_limit_cad
    if snapshot.quantity is not None:
        item = snapshot.quantity if item <= 0 else min(item, snapshot.quantity)
    if snapshot.amount_cad is not None:
        live = float(snapshot.amount_cad)
        value = live if value <= 0 else min(value, live)
    return item, value

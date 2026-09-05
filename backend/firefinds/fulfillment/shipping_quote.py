"""Parse observed Randmar quote amounts without inventing free shipping/ETAs."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .supplier_product import nonnegative_amount


@dataclass(frozen=True)
class ShippingQuote:
    method_id: str
    label: str
    charge_upper_bound: Decimal


def parse_shipping_quotes(raw):
    group = raw.get("ShippingMethods") if isinstance(raw, dict) else None
    methods = group.get("Methods") if isinstance(group, dict) else None
    if not isinstance(methods, list) or not methods:
        raise ValueError("Shipping methods unresolved")
    result, seen = [], set()
    for row in methods:
        if not isinstance(row, dict):
            raise ValueError("Malformed shipping method")
        method_id, label = row.get("MethodId"), row.get("Label")
        if not isinstance(method_id, str) or not method_id.strip() or method_id in seen:
            raise ValueError("Shipping method identity unresolved")
        if not isinstance(label, str) or not label.strip():
            raise ValueError("Shipping service unresolved")
        seen.add(method_id)
        fees = nonnegative_amount(row.get("Fees"))
        real = nonnegative_amount(row.get("RealShippingCharges"))
        # Do not subtract promotional discounts whose application is unverified.
        # Missing either cost field is not zero. Date is NOT assumed to be ETA.
        result.append(ShippingQuote(method_id, label, max(fees, real)))
    return tuple(sorted(result, key=lambda q: (q.charge_upper_bound, q.method_id)))

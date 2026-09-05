"""Pure fulfillment preparation from explicit mappings and fresh supplier data.

No API writes exist here. Caller must obtain the current buyer-destination quote
and net unit sale revenue (after discounts, excluding collected tax).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal as D
from typing import Any, Mapping

from firefinds.engine.models import Candidate
from firefinds.engine.order_ingest import map_ebay_order, MAPPED
from firefinds.engine.services import OpportunityEngine
from .randmar_checkout import build_process_cart_input


@dataclass
class FulfillmentPreview:
    order_id: str
    allowed: bool
    reason: str
    supplier_sku: str | None = None
    quantity: int = 0
    payload: dict[str, Any] = field(default_factory=dict, repr=False)

    def summary(self):
        return {"order_id": self.order_id, "allowed": self.allowed,
                "reason": self.reason, "supplier_sku": self.supplier_sku,
                "quantity": self.quantity, "payload_fields": sorted(self.payload),
                "submitted": False}


def prepare_fulfillment(*, settings, order: Mapping[str, Any],
                        sku_mapping: Mapping[str, str], supplier: Candidate,
                        shipping_method_id: str, unit_sale_revenue: D,
                        quote_observed_at: float, now: float,
                        max_quote_age_sec: int = 300) -> FulfillmentPreview:
    """Preview a single-line order; input shipping is the per-unit landed quote.

    This is not approval to buy. PO reconciliation, refreshed payment status,
    submission gates, and the durable submission guard remain required.
    """
    record = map_ebay_order(order)
    result = FulfillmentPreview(record.ebay_order_id, False, record.reason)
    if record.state != MAPPED:
        return result
    mapped = sku_mapping.get(record.sku)
    if not mapped or mapped != supplier.sku:
        result.reason = "unverified_supplier_mapping"
        return result
    result.supplier_sku = mapped
    result.quantity = record.qty
    age = D(str(now)) - D(str(quote_observed_at))
    if not age.is_finite() or max_quote_age_sec <= 0 or not D("0") <= age <= max_quote_age_sec:
        result.reason = "stale_or_invalid_supplier_quote"
        return result
    # An already-paid order must clear the profit floor, not a competitor's
    # newer asking price. Never reject profitable fulfillment because another
    # seller raised its price after the buyer checked out.
    decision = OpportunityEngine(settings).evaluate(replace(supplier, competitor_price=None))
    if not decision.allowed:
        result.reason = decision.reason
        return result
    if record.qty > decision.quantity:
        result.reason = "insufficient_buffered_stock"
        return result
    if not unit_sale_revenue.is_finite() or unit_sale_revenue < decision.price:
        result.reason = "sale_below_safe_price"
        return result
    ship = record.ship_to
    try:
        payload = build_process_cart_input(
            {"name": ship["Name"], "street1": ship["Street1"], "street2": ship["Street2"],
             "city": ship["City"], "province": ship["Province"], "postal_code": ship["PostalCode"],
             "country": ship["Country"], "phone": ship["ContactPhone"]},
            ebay_order_id=record.ebay_order_id, shipping_method_id=shipping_method_id,
            allow_partial_shipment=False,
        )
    except ValueError:
        result.reason = "incomplete_supplier_checkout_fields"
        return result
    result.allowed = True
    result.reason = "held_before_supplier_submission"
    result.payload = payload
    return result

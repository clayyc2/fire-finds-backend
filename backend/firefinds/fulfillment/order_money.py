"""Conservative CAD single-line economics from eBay TAX_BREAKDOWN responses.

This normalizes revenue, not supplier tax treatment or a final fee guarantee.
Ambiguous adjustments, refunds and special programs require review.
Source contract: eBay Fulfillment OpenAPI v1.20.7 PricingSummary/LineItem/Order.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal as D, InvalidOperation


@dataclass(frozen=True)
class OrderMoney:
    quantity: int
    item_revenue: D
    delivery_revenue: D
    revenue: D
    tax: D
    fee_basis: D
    accrued_marketplace_fees: D

    @property
    def unit_item_price(self):
        return self.item_revenue / self.quantity

    @property
    def unit_revenue(self):
        return self.revenue / self.quantity


def amount(raw, *, negative=False):
    if not isinstance(raw, dict) or raw.get("currency") != "CAD" or not isinstance(raw.get("value"), str):
        raise ValueError("CAD monetary amount required")
    try:
        value = D(raw["value"])
    except InvalidOperation:
        raise ValueError("Invalid monetary amount") from None
    if not value.is_finite() or (value > 0 if negative else value < 0):
        raise ValueError("Invalid monetary sign or value")
    try:
        rounded = value.quantize(D("0.01"))
    except InvalidOperation:
        raise ValueError("Monetary amount outside supported precision") from None
    if value != rounded:
        raise ValueError("Fractional-cent monetary amount unresolved")
    return value


def optional_amount(record, key, *, negative=False):
    # Missing conditional fields are absent, but explicit null/malformed is NOT zero.
    return amount(record[key], negative=negative) if key in record else D(0)


def tax_total(line):
    merged = {}
    for field in ("taxes", "ebayCollectAndRemitTaxes"):
        rows = line.get(field, [])
        if not isinstance(rows, list):
            raise ValueError("Tax breakdown unresolved")
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Tax breakdown unresolved")
            kind = row.get("taxType")
            if kind not in {"GST", "PROVINCE_SALES_TAX"} or kind in seen:
                raise ValueError("Unsupported or duplicate tax type")
            seen.add(kind)
            value = amount(row.get("amount"))
            if kind in merged and merged[kind] != value:
                raise ValueError("Conflicting tax representations")
            merged[kind] = value
    # eBay explicitly permits the same tax to appear in both arrays. Count once.
    return sum(merged.values(), D(0))


def parse_order_money(order):
    if not isinstance(order, dict) or order.get("orderPaymentStatus") != "PAID":
        raise ValueError("Paid order required")
    lines = order.get("lineItems")
    if not isinstance(lines, list) or len(lines) != 1 or not isinstance(lines[0], dict):
        raise ValueError("Single-line order required")
    line = lines[0]
    qty = line.get("quantity")
    if type(qty) is not int or qty <= 0:
        raise ValueError("Positive integral quantity required")
    payment = order.get("paymentSummary")
    pricing = order.get("pricingSummary")
    if not isinstance(payment, dict) or not isinstance(pricing, dict):
        raise ValueError("Payment and pricing summary required")
    for record in (line, payment):
        refunds = record.get("refunds", [])
        if not isinstance(refunds, list) or refunds:
            raise ValueError("Refund requires review")
    if order.get("program") or line.get("ebayCollectedCharges") or line.get("giftDetails"):
        raise ValueError("Special program economics require review")
    if optional_amount(pricing, "adjustment") != 0 or optional_amount(pricing, "fee") != 0:
        raise ValueError("Adjustments or regulatory fees require review")
    subtotal = amount(pricing.get("priceSubtotal"))
    if subtotal != amount(line.get("lineItemCost")):
        raise ValueError("Line and order subtotal mismatch")
    item = subtotal + optional_amount(pricing, "priceDiscount", negative=True)
    if "discountedLineItemCost" in line and amount(line["discountedLineItemCost"]) != item:
        raise ValueError("Discounted line and order mismatch")
    delivery = amount(pricing.get("deliveryCost")) + optional_amount(pricing, "deliveryDiscount", negative=True)
    if item <= 0 or delivery < 0:
        raise ValueError("Invalid net item or delivery revenue")
    declared_tax = optional_amount(pricing, "tax")
    line_tax = tax_total(line)
    if declared_tax and line_tax and declared_tax != line_tax:
        raise ValueError("Line and order tax mismatch")
    tax = max(declared_tax, line_tax)
    revenue = item + delivery
    gross = amount(pricing.get("total"))
    if gross != revenue + tax:
        raise ValueError("Tax-inclusive total does not reconcile")
    # Accrued fees are not a final upper bound. Worker still requires explicit
    # complete fee evidence, at least this amount AND configured conservative fees.
    fees = optional_amount(order, "totalMarketplaceFee")
    basis = max(gross, optional_amount(order, "totalFeeBasisAmount"))
    return OrderMoney(qty, item, delivery, revenue, tax, basis, fees)

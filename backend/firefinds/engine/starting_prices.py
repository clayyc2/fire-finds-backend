"""User-authorized estimated-cost starting prices; no market/network access.

Finalizes a business price, NOT supplier cost evidence or permission to publish.
Buyer-specific checkout must still revalidate actual cost before purchasing.
"""
from __future__ import annotations

from decimal import Decimal as D, ROUND_CEILING

from .catalogue_queue import number


def cents(value):
    return value.quantize(D("0.01"), rounding=ROUND_CEILING)


def starting_price(*, cost, map_price, weight_lb, settings):
    cost, map_price, weight = number(cost), number(map_price), number(weight_lb)
    if cost is None or cost <= 0 or map_price is None:
        raise ValueError("Valid supplier cost and MAP required")
    names = ("estimated_shipping_small_cad", "estimated_shipping_other_cad",
        "supplier_cost_contingency_pct", "estimated_fee_rate", "fee_tax_basis_contingency_pct",
        "return_reserve_pct", "estimated_fee_fixed_cad", "target_profit_pct",
        "min_contribution_margin", "min_contribution_profit_cad", "ebay_fee_rate", "ebay_fee_fixed")
    p = {name: number(getattr(settings, name)) for name in names}
    if any(v is None for v in p.values()):
        raise ValueError("Finite nonnegative pricing settings required")
    shipping = cents(p["estimated_shipping_small_cad"] if weight is not None and weight <= 2
                     else p["estimated_shipping_other_cad"])
    if shipping <= 0:
        raise ValueError("Positive shipping allowance required")
    landed = cents((cost + shipping) * (1 + p["supplier_cost_contingency_pct"]))
    fee_rate = max(p["estimated_fee_rate"], p["ebay_fee_rate"]) * (1 + p["fee_tax_basis_contingency_pct"])
    variable = fee_rate + p["return_reserve_pct"]
    fixed = max(p["estimated_fee_fixed_cad"], p["ebay_fee_fixed"])
    margin = max(p["target_profit_pct"], p["min_contribution_margin"])
    if variable + margin >= 1:
        raise ValueError("Cost/fee/margin settings leave no positive revenue denominator")
    # Include separate buyer-paid shipping in revenue and platform fee basis.
    total_floor = max((landed + fixed) / (1 - variable - margin),
                      (landed + fixed + p["min_contribution_profit_cad"]) / (1 - variable))
    item = cents(max(D("0.01"), map_price, total_floor - shipping))
    total = item + shipping
    # Round allowances upward and recheck the exact profit after those reserves.
    while True:
        fees, returns = cents(total * fee_rate + fixed), cents(total * p["return_reserve_pct"])
        profit = total - landed - fees - returns
        if profit >= p["min_contribution_profit_cad"] and profit / total >= margin:
            break
        item += D("0.01")
        total = item + shipping
    return {"item_price_cad": str(item), "buyer_shipping_cad": str(shipping),
        "total_before_buyer_tax_cad": str(total), "estimated_landed_cost_cad": str(landed),
        "estimated_fees_cad": str(fees), "return_reserve_cad": str(returns),
        "estimated_profit_cad": str(profit), "estimated_margin": str(profit / total),
        "price_basis": "user_authorized_conservative_estimates",
        "shipping_cost_verified": False, "profit_guaranteed": False}


def price_queue(queue_report, catalogue_rows, settings):
    rows = {}
    for row in catalogue_rows:
        sku = row.get("RandmarSKU")
        if not sku or sku in rows:
            raise ValueError("Unique catalogue identities required")
        rows[sku] = row
    result = dict(queue_report)
    priced, seen = [], set()
    for item in queue_report["queue"]:
        sku = item["sku"]
        if sku in seen or sku not in rows:
            raise ValueError("Missing or repeated pricing identity")
        seen.add(sku)
        source = rows[sku]
        if number(source.get("Price")) != number(item["dealer_cost_cad"]) or number(source.get("MAP")) != number(item["map_cad"]):
            raise ValueError("Queue and catalogue costs disagree")
        price = starting_price(cost=item["dealer_cost_cad"], map_price=item["map_cad"],
                               weight_lb=source.get("UnitWeight"), settings=settings)
        priced.append(dict(item, final_price_cad=price["item_price_cad"], starting_price=price,
                           publish_ready=False, pricing_status="STARTING_PRICE_SET"))
    result.update(queue=priced, priced_count=len(priced), ready_to_publish_count=0)
    return result

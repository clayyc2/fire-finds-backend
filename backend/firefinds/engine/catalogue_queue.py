"""Offline opinion-first catalogue queue; only first-party results can teach it.

No network, AI, supplier percentile ranks, competitor prices or outside sales
data. Ranking is a prioritization opinion, NOT a measured sales probability.
The queue does not authorize publishing or fabricate missing checkout evidence.
"""
from __future__ import annotations

from decimal import Decimal as D, InvalidOperation


def number(raw):
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = D(str(raw))
    except InvalidOperation:
        return None
    return value if value.is_finite() and value >= 0 else None


def result_key(result):
    if not isinstance(result, dict) or result.get("source") != "fire_finds_own_results":
        raise ValueError("Only explicit Fire Finds results accepted")
    days, profit = number(result.get("exposure_days")), result.get("net_profit_cad")
    try:
        profit = D(str(profit))
    except InvalidOperation:
        raise ValueError("Invalid own-result profit") from None
    sold, returned = result.get("fulfilled_units"), result.get("returned_units")
    if (days is None or days <= 0 or not profit.is_finite() or
            type(sold) is not int or type(returned) is not int or not 0 <= returned <= sold):
        raise ValueError("Invalid own-result observations")
    # A week's exposure is needed before zero sales count as a weak result.
    if days < 7:
        return None
    retained = sold - returned
    group = 3 if retained > 0 and profit > 0 else 1
    return group, D(retained) / days, profit / days


def opinion_score(row):
    kind = str(row.get("ProductType") or "").lower()
    # Opinion: prioritize repeat-use office consumables, then small accessories.
    category = D(10)
    if any(x in kind for x in ("toner", "inkjet", "ink cartridge")):
        category = D(50)
    elif any(x in kind for x in ("label", "tape", "pen", "marker", "paper")):
        category = D(40)
    elif any(x in kind for x in ("cable", "mouse", "keyboard", "adapter")):
        category = D(25)
    cost, weight, stock = number(row.get("Price")), number(row.get("UnitWeight")), number(row.get("AvailableQuantity"))
    score = category + (D(20) / (1 + cost / 50) if cost is not None else 0)
    score += D(15) / (1 + weight) if weight is not None else 0
    score += min(stock, D(50)) / 5 if stock is not None else 0
    return score


def build_catalogue_queue(rows, *, own_results=None, existing_skus=(), stock_buffer=2,
                          initial_quantity=1, purchase_denied_skus=()):
    if type(stock_buffer) is not int or stock_buffer < 0 or type(initial_quantity) is not int or initial_quantity < 1:
        raise ValueError("Invalid quantity controls")
    own_results = own_results or {}
    if not isinstance(own_results, dict):
        raise ValueError("SKU-keyed own results required")
    existing, denied, seen = set(existing_skus), set(purchase_denied_skus), set()
    ranked, held = [], []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Catalogue row must be an object")
        sku = row.get("RandmarSKU")
        if not isinstance(sku, str) or not sku.strip() or sku in seen:
            raise ValueError("Missing or duplicate catalogue SKU")
        seen.add(sku)
        reasons = []
        cost, stock, weight, map_price = (number(row.get(k)) for k in
            ("Price", "AvailableQuantity", "UnitWeight", "MAP"))
        title = str(row.get("Title") or row.get("RandmarTitle") or "").strip()
        kind = str(row.get("ProductType") or "").lower()
        if sku in existing: reasons.append("ALREADY_LISTED")
        if sku in denied: reasons.append("SUPPLIER_PURCHASE_RESTRICTED")
        if row.get("State") != "Active": reasons.append("NOT_ACTIVE")
        if row.get("OpportunityOnly") is not False: reasons.append("OPPORTUNITY_UNRESOLVED_OR_RESTRICTED")
        if cost is None or cost <= 0 or map_price is None: reasons.append("COST_OR_MAP_UNRESOLVED")
        if stock is None or stock != stock.to_integral_value() or stock <= stock_buffer:
            reasons.append("STOCK_BUFFER")
        if not title: reasons.append("TITLE_UNRESOLVED")
        if weight is not None and weight > 30: reasons.append("HEAVY_RETURN_RISK")
        if any(term in kind for term in ("contract", "warrant", "software", "service plan", "medical", "supplement")):
            reasons.append("SPECIAL_PROGRAM_OR_RETURN_RISK")
        item = {"sku": sku, "title": title, "brand": row.get("ManufacturerName"),
                "product_type": row.get("ProductType"), "dealer_cost_cad": str(cost) if cost is not None else None,
                "map_cad": str(map_price) if map_price is not None else None,
                "publish_ready": False, "final_price_cad": None}
        if reasons:
            item["hold_reasons"] = reasons
            held.append(item)
            continue
        own = result_key(own_results[sku]) if sku in own_results else None
        score = opinion_score(row)
        item.update(initial_quantity=min(initial_quantity, int(stock)-stock_buffer),
                    ranking_basis="fire_finds_own_results" if own else "catalogue_opinion_only",
                    opinion_score=str(score.quantize(D("0.0001"))),
                    readiness_required=["fresh_supplier_product", "ebay_channel_permission", "return_and_media_policy",
                        "destination_shipping_and_service", "complete_cost_price", "fulfillment_e2e_and_runner",
                        "ebay_category_and_required_aspects", "fresh_capacity_reservation"])
        key = own if own else (2, score, D(0))
        ranked.append((key, item))
    ranked.sort(key=lambda pair: (-pair[0][0], -pair[0][1], -pair[0][2], pair[1]["sku"]))
    queue = [item for _, item in ranked]
    for rank, item in enumerate(queue, 1):
        item["rank"] = rank
    return {"catalogue_count": len(seen), "candidate_count": len(queue), "held_count": len(held),
            "ready_to_publish_count": 0, "market_research_used": False, "ai_runtime_required": False,
            "ranking_is_sales_probability": False, "queue": queue, "held": sorted(held, key=lambda r: r["sku"])}

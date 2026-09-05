from dataclasses import replace
from decimal import Decimal as D

import pytest

from firefinds.config import Settings
from firefinds.engine.catalogue_queue import build_catalogue_queue
from firefinds.engine.starting_prices import starting_price, price_queue


@pytest.mark.parametrize("cost", ["0.01", "10.58", "100", "10000"])
@pytest.mark.parametrize("weight,shipping", [(0.1, "49.95"), (2, "49.95"), (3, "99.95"), (None, "99.95")])
def test_conservative_price_has_margin_and_dollar_floor(cost, weight, shipping):
    p = starting_price(cost=cost, map_price=0, weight_lb=weight, settings=Settings())
    total = D(p["item_price_cad"]) + D(shipping)
    profit = total - sum(D(p[k]) for k in ("estimated_landed_cost_cad", "estimated_fees_cad", "return_reserve_cad"))
    assert profit >= 8 and profit / total >= D("0.18")
    assert p["buyer_shipping_cad"] == shipping
    assert p["profit_guaranteed"] is False and p["shipping_cost_verified"] is False


def test_map_is_item_only_not_total_with_shipping():
    p = starting_price(cost=10, map_price=250, weight_lb=1, settings=Settings())
    assert D(p["item_price_cad"]) >= 250


@pytest.mark.parametrize("setting,value", [("estimated_fee_rate", 1), ("target_profit_pct", 1),
    ("estimated_shipping_small_cad", -1), ("return_reserve_pct", float("nan"))])
def test_invalid_policy_refused(setting, value):
    with pytest.raises(ValueError):
        starting_price(cost=10, map_price=0, weight_lb=1, settings=replace(Settings(), **{setting: value}))


def row(sku="R1"):
    return {"RandmarSKU": sku, "Price": 10, "MAP": 0, "UnitWeight": 1,
            "State": "Active", "OpportunityOnly": False, "AvailableQuantity": 20,
            "Title": "Office supplies", "ProductType": "Labels"}


def test_every_candidate_priced_without_publishing_or_rank_change():
    rows = [row(str(i)) for i in range(250)]
    queue = build_catalogue_queue(rows)
    report = price_queue(queue, rows, Settings())
    assert report["priced_count"] == 250 and report["ready_to_publish_count"] == 0
    assert [r["sku"] for r in queue["queue"]] == [r["sku"] for r in report["queue"]]
    assert all(r["final_price_cad"] and not r["publish_ready"] for r in report["queue"])
    assert all(r["final_price_cad"] is None for r in queue["queue"])


def test_price_rejects_changed_cost_identity():
    rows = [row()]
    queue = build_catalogue_queue(rows)
    rows[0]["Price"] = 11
    with pytest.raises(ValueError):
        price_queue(queue, rows, Settings())

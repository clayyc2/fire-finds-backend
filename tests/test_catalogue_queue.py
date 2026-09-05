from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D

import pytest

from firefinds.clients.ebay import EbayClient, EbayListingsDisabled
from firefinds.config import Settings
from firefinds.engine.catalogue_queue import build_catalogue_queue
from firefinds.engine.models import Candidate
from firefinds.engine.services import OpportunityEngine
from firefinds.pipelines.authorize import authorize_sku


def row(sku="A", **changes):
    return {"RandmarSKU": sku, "Title": "Ink", "ProductType": "Inkjets", "Price": 10,
        "MAP": 20, "AvailableQuantity": 20, "UnitWeight": 1, "State": "Active", "OpportunityOnly": False, **changes}


def test_full_queue_one_unit_per_new_sku_and_no_prices_fabricated():
    report = build_catalogue_queue([row(str(i)) for i in range(200)])
    assert report["candidate_count"] == 200
    assert report["ready_to_publish_count"] == 0
    assert not report["market_research_used"]
    assert all(r["initial_quantity"] == 1 and r["final_price_cad"] is None for r in report["queue"])


def test_external_demand_and_price_fields_do_not_affect_ranking():
    rows = [row("A"), row("B", Price=20)]
    first = build_catalogue_queue(rows)
    changed = deepcopy(rows)
    changed[1].update(OverallPercentileRank=100, SalesStatistics=99999, competitor_price=.01,
                      ManufacturerPercentileRank=100, sales_probability=1)
    assert build_catalogue_queue(changed) == first


def test_only_own_mature_results_override_opinion():
    rows = [row("A"), row("B", Price=100), row("C")]
    def result(sold):
        return {"source": "fire_finds_own_results", "exposure_days": 14,
            "fulfilled_units": sold, "returned_units": 0, "net_profit_cad": "50"}
    report = build_catalogue_queue(rows, own_results={"B": result(5), "C": result(0)})
    assert [r["sku"] for r in report["queue"]] == ["B", "A", "C"]
    assert report["queue"][0]["ranking_basis"] == "fire_finds_own_results"
    bad = result(5)
    bad["source"] = "competitor_sales"
    with pytest.raises(ValueError): build_catalogue_queue(rows, own_results={"A": bad})


def test_known_holds_are_not_eligible_candidates():
    rows = [row("A"), row("B"), row("C", OpportunityOnly=True), row("D", AvailableQuantity=2),
            row("E", UnitWeight=31), row("F", MAP=None), row("G", ProductType="Contract Toners")]
    report = build_catalogue_queue(rows, existing_skus=["A"], purchase_denied_skus=["B"])
    assert report["candidate_count"] == 0 and report["held_count"] == 7


def test_duplicate_sku_fails_instead_of_allocating_twice():
    with pytest.raises(ValueError): build_catalogue_queue([row(), row()])


def test_research_disabled_before_credentials_or_network(monkeypatch):
    client = EbayClient(Settings())
    monkeypatch.setattr(client, "require_credentials", lambda: pytest.fail("Must not load credentials"))
    for call in (lambda: client.fetch_app_token(), lambda: client.search_item_summary(q="ink"),
                 lambda: client.competition_for_product({"upc": "123456789012"})):
        with pytest.raises(EbayListingsDisabled): call()


def test_default_price_ignores_cached_comparables():
    c = Candidate("A", D(20), D(10), 10, map_price=D(0), channel_allowed=True)
    engine = OpportunityEngine(Settings())
    expected = engine.evaluate(c)
    assert expected.price == engine.evaluate(replace(c, competitor_price=D(999), competition_score=D(999))).price
    assert expected.rank_score == engine.evaluate(replace(c, competitor_price=D(999), competition_score=D(999))).rank_score
    assert expected.margin >= D(".18") and expected.profit >= 8


def test_non_opportunity_status_does_not_grant_channel_permission():
    base = {"map": 20, "sell_comp": 30, "opportunity_only": False}
    assert not authorize_sku(base)["channel_ok"]
    assert not authorize_sku({**base, "channel_allowed": True})["channel_ok"]
    assert authorize_sku({**base, "channel_allowed": True, "channel_evidence": "fixture approval"})["channel_ok"]

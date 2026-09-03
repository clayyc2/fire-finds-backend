"""Shipping quote parsing + UNRESOLVED blocks final listable."""

from __future__ import annotations

from firefinds.clients.ebay import CompetitionSnapshot
from firefinds.config import Settings
from firefinds.scoring.competition import evaluate_listable
from firefinds.scoring.shipping import (
    InjectedQuoteProvider,
    STATUS_RESOLVED,
    STATUS_UNRESOLVED,
    compute_landed_cost_with_quote,
    parse_cart_shipping_methods,
    parse_shipvia_estimates,
)


def test_parse_cart_shipping_methods_picks_cheapest(cart_shipping_fixture):
    q = parse_cart_shipping_methods(cart_shipping_fixture)
    assert q.status == STATUS_RESOLVED
    assert q.cost_cad == 18.75
    assert q.method_id == "STD"


def test_parse_shipvia_estimates():
    q = parse_shipvia_estimates(
        [
            {"Carrier": "Purolator", "CarrierCode": "Puro", "Price": 22.5},
            {"Carrier": "UPS", "CarrierCode": "UPS", "Price": 19.0},
        ]
    )
    assert q.resolved
    assert q.cost_cad == 19.0


def test_empty_methods_unresolved():
    q = parse_cart_shipping_methods({"ShippingMethods": {"Methods": []}})
    assert q.status == STATUS_UNRESOLVED
    assert q.cost_cad is None


def test_injected_provider_unresolved_by_default():
    p = InjectedQuoteProvider()
    q = p.quote_product({"sku": "X"}, ship_to={})
    assert q.status == STATUS_UNRESOLVED


def test_unresolved_shipping_blocks_listable(settings: Settings):
    snap = CompetitionSnapshot(
        query="upc",
        query_type="upc",
        item_count=5,
        lowest_price=100.0,
        median_price=110.0,
        sample_url="https://ebay.ca/itm/1",
    )
    product = {
        "sku": "A",
        "map": 100.0,
        "dealer_cost": 40.0,
        "net_cost": 40.0,
        "rebate": 0,
        "stock": 10,
        "opportunity_only": False,
    }
    result = evaluate_listable(
        product,
        snap,
        settings,
        shipping_status=STATUS_UNRESOLVED,
        shipping_cost_cad=None,
        provisional_public_ebay=False,
        needs_official_ebay_validation=False,
    )
    assert result.listable_pass is False
    assert result.final_profitability is False
    assert "shipping_unresolved" in result.reasons
    assert result.rank_score == 0.0


def test_resolved_shipping_can_pass(settings: Settings):
    snap = CompetitionSnapshot(
        query="upc",
        query_type="upc",
        item_count=5,
        lowest_price=100.0,
        median_price=110.0,
        sample_url="https://ebay.ca/itm/1",
    )
    product = {
        "sku": "A",
        "map": 100.0,
        "dealer_cost": 40.0,
        "net_cost": 40.0,
        "rebate": 0,
        "stock": 10,
        "opportunity_only": False,
    }
    result = evaluate_listable(
        product,
        snap,
        settings,
        shipping_status=STATUS_RESOLVED,
        shipping_cost_cad=18.75,
        provisional_public_ebay=False,
        needs_official_ebay_validation=False,
    )
    assert result.listable_pass is True
    assert result.final_profitability is True
    assert result.shipping_cost_cad == 18.75
    # profit = 100 - (13.25+0.30) - 18.75 - 40 = 27.7
    assert abs(result.contribution_profit - 27.7) < 1e-6


def test_landed_requires_resolved_quote():
    product = {"dealer_cost": 50.0, "rebate": 0}
    landed, q = compute_landed_cost_with_quote(
        product, InjectedQuoteProvider().quote_product({"sku": "Z"}, ship_to={})
    )
    assert landed is None
    assert q.status == STATUS_UNRESOLVED

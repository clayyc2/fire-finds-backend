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


from firefinds.scoring.shipping import (
    REPRESENTATIVE_DESTINATIONS,
    SHIPTO_LOCATION_FIELDS,
    DestinationQuote,
    ShippingQuote,
    aggregate_destination_quotes,
    destination_to_shipto,
    flag_expensive_destinations,
    percentile_linear,
    quote_representative_destinations,
    shipto_for_api,
)
from firefinds.services_quote import quote_eligible_skus
from firefinds.services import ingest_stub
from firefinds.db.schema import init_db


def test_shipto_location_has_required_fields():
    for dest in REPRESENTATIVE_DESTINATIONS:
        loc = destination_to_shipto(dest)
        assert tuple(loc.keys()) == SHIPTO_LOCATION_FIELDS
        assert loc["Province"] == dest.province
        assert len(loc["Province"]) == 2
        assert loc["Country"] == "CA"
        assert loc["PostalCode"] == dest.postal_code
        assert loc["Street1"]
        assert loc["Street2"] == ""
        assert loc["City"] == dest.city
    # extras stripped for additionalProperties=false
    stripped = shipto_for_api({"Name": "X", "City": "Calgary", "dest_id": "calgary"})
    assert "dest_id" not in stripped
    assert set(stripped) == set(SHIPTO_LOCATION_FIELDS)


def test_percentile_75_five_values():
    # linear: k = 4 * 0.75 = 3 → 4th of 5 = 20
    assert percentile_linear([10, 12, 15, 20, 40], 75) == 20.0


def test_percentile_75_four_values():
    # k = 3 * 0.75 = 2.25 → 15 + 0.25 * 5 = 16.25
    assert abs(percentile_linear([10, 12, 15, 20], 75) - 16.25) < 1e-9


def test_percentile_75_one_value_and_empty():
    assert percentile_linear([18.0], 75) == 18.0
    assert percentile_linear([], 75) is None


def test_aggregate_p75_and_zero_resolved():
    dests = REPRESENTATIVE_DESTINATIONS
    costs = [10.0, 12.0, 15.0, 20.0, 40.0]
    quotes = [
        DestinationQuote(
            destination=dests[i],
            quote=ShippingQuote(status=STATUS_RESOLVED, cost_cad=costs[i], source="injected"),
        )
        for i in range(5)
    ]
    bundle = aggregate_destination_quotes(quotes)
    assert bundle.resolved
    assert bundle.p75_cad == 20.0
    assert bundle.resolved_n == 5

    unresolved = [
        DestinationQuote(
            destination=d,
            quote=ShippingQuote.unresolved(reason="x", source="injected"),
        )
        for d in dests
    ]
    empty = aggregate_destination_quotes(unresolved)
    assert empty.status == STATUS_UNRESOLVED
    assert empty.shipping_cost_cad is None
    assert empty.resolved_n == 0


def test_aggregate_p75_over_partial_resolves():
    dests = REPRESENTATIVE_DESTINATIONS
    quotes = []
    for i, d in enumerate(dests):
        if i < 3:
            q = ShippingQuote(status=STATUS_RESOLVED, cost_cad=float(10 + i), source="injected")
        else:
            q = ShippingQuote.unresolved(reason="miss", source="injected")
        quotes.append(DestinationQuote(destination=d, quote=q))
    bundle = aggregate_destination_quotes(quotes)
    assert bundle.resolved
    assert bundle.resolved_n == 3
    # p75 of [10, 11, 12]: k = 2 * 0.75 = 1.5 → 11.5
    assert abs(bundle.p75_cad - 11.5) < 1e-9


def test_expensive_destination_flag_when_p75_passes():
    # sell 100, net 40, fees 13.55 → profit = 46.45 - ship; 12% needs ship <= 34.45
    dest_costs = {
        "calgary": 10.0,
        "vancouver": 12.0,
        "toronto": 15.0,
        "montreal": 20.0,
        "halifax": 50.0,  # fails floors
    }
    # p75 of those five is 20 → profit 26.45, margin 0.2645 (passes)
    p75 = percentile_linear(list(dest_costs.values()), 75)
    assert p75 == 20.0
    flag = flag_expensive_destinations(
        dest_costs,
        sell_price=100.0,
        net_cost=40.0,
        rebate=0.0,
        min_profit_cad=8.0,
        min_margin=0.12,
    )
    assert flag.fails_expensive_destinations is True
    assert "Halifax" in flag.failed_cities
    assert flag.failed_dest_ids == ("halifax",)
    # p75 itself still passes floors
    from firefinds.scoring.filters import compute_contribution

    profit, margin, _ = compute_contribution(100.0, 40.0, 0.0, ship_est_cad=p75)
    assert profit >= 8.0
    assert margin >= 0.12


def test_expensive_flag_false_when_all_dests_pass():
    dest_costs = {d.dest_id: 12.0 for d in REPRESENTATIVE_DESTINATIONS}
    flag = flag_expensive_destinations(
        dest_costs,
        sell_price=100.0,
        net_cost=40.0,
        min_profit_cad=8.0,
        min_margin=0.12,
    )
    assert flag.fails_expensive_destinations is False
    assert flag.failed_cities == ()


def test_quote_representative_injected_dest_costs():
    provider = InjectedQuoteProvider(
        dest_costs={
            "calgary": 10.0,
            "vancouver": 12.0,
            "toronto": 15.0,
            "montreal": 20.0,
            "halifax": 40.0,
        }
    )
    bundle = quote_representative_destinations(provider, {"sku": "X", "stock": 10})
    assert bundle.resolved
    assert bundle.p75_cad == 20.0
    assert bundle.resolved_n == 5


def test_quote_eligible_checkpoint_and_flags(settings: Settings):
    ingest_stub(settings)
    provider = InjectedQuoteProvider(
        dest_costs={
            "calgary": 10.0,
            "vancouver": 12.0,
            "toronto": 15.0,
            "montreal": 20.0,
            "halifax": 50.0,
        }
    )
    summary = quote_eligible_skus(
        settings=settings,
        quote_provider=provider,
        sleep_sec=0.0,
        resume=True,
    )
    assert summary["quoted"] >= 1
    conn = init_db(settings.db_path)
    n = conn.execute("SELECT COUNT(*) FROM shipping_quotes").fetchone()[0]
    assert n >= 5
    # resume skips
    summary2 = quote_eligible_skus(
        settings=settings,
        quote_provider=provider,
        sleep_sec=0.0,
        resume=True,
    )
    assert summary2["skipped_cached"] >= 1
    assert summary2["quoted"] == 0

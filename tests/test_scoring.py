"""Unit tests for deterministic scoring filters (with fee placeholders)."""

from __future__ import annotations

from firefinds.scoring.filters import (
    ScoreThresholds,
    compute_contribution,
    resolve_sell_price,
    score_product,
)


def test_compute_contribution_basic():
    # sell 100, fees = 13.25+0.30=13.55, ship 10, landed 50 → profit 26.45
    profit, margin, fees = compute_contribution(100.0, 50.0, rebate=0.0)
    assert abs(fees - 13.55) < 1e-9
    assert abs(profit - 26.45) < 1e-9
    assert abs(margin - 0.2645) < 1e-9


def test_compute_contribution_with_rebate():
    profit, margin, fees = compute_contribution(100.0, 50.0, rebate=5.0)
    assert abs(profit - 31.45) < 1e-9
    assert abs(margin - 0.3145) < 1e-9
    assert abs(fees - 13.55) < 1e-9


def test_compute_contribution_zero_sell_price():
    profit, margin, fees = compute_contribution(0.0, 10.0)
    assert profit == -20.0  # 0 - 0 - 10 - 10 + 0
    assert margin == 0.0
    assert fees == 0.0


def test_resolve_sell_price_map_preferred():
    assert resolve_sell_price({"map": 50, "msrp": 100}) == 50.0


def test_resolve_sell_price_msrp_discount():
    assert abs(resolve_sell_price({"map": 0, "msrp": 100}) - 95.0) < 1e-9


def test_pass_all_gates():
    # sell 100; fees 13.55; ship 10; landed 50 → profit 26.45; margin 0.2645; stock 10
    product = {
        "sku": "OK-1",
        "map": 100.0,
        "landed_cost": 50.0,
        "rebate": 0,
        "stock": 10,
    }
    result = score_product(product)
    assert result.passed is True
    assert result.score == result.contribution_profit
    assert abs(result.contribution_profit - 26.45) < 1e-9
    assert result.reasons == ("ok",)


def test_fail_profit_below_threshold():
    # sell 20; fees=2.95; ship 10; landed 16.5 → profit -9.45
    product = {
        "sku": "LOW-PROFIT",
        "map": 20.0,
        "landed_cost": 16.5,
        "stock": 5,
    }
    result = score_product(product)
    assert result.passed is False
    assert result.score == 0.0
    assert any(r.startswith("profit_below_") for r in result.reasons)


def test_fail_margin_below_threshold():
    # Need profit >= 8 but margin < 0.12.
    # sell 200; fees=26.8; ship 10; landed 156 → profit 7.2 — too low profit
    # sell 200; fees=26.8; ship 10; landed 147 → profit 16.2; margin 0.081 < 0.12
    product = {
        "sku": "LOW-MARGIN",
        "map": 200.0,
        "landed_cost": 147.0,
        "stock": 10,
    }
    result = score_product(product)
    assert result.passed is False
    assert result.contribution_profit >= 8.0
    assert any(r.startswith("margin_below_") for r in result.reasons)


def test_fail_stock_buffer():
    product = {
        "sku": "LOW-STOCK",
        "map": 100.0,
        "landed_cost": 50.0,
        "stock": 2,
    }
    th = ScoreThresholds(stock_buffer=2)
    result = score_product(product, th)
    assert result.passed is False
    assert any(r.startswith("stock_leq_buffer_") for r in result.reasons)


def test_stock_just_above_buffer_passes():
    product = {
        "sku": "OK-STOCK",
        "map": 100.0,
        "landed_cost": 50.0,
        "stock": 3,
    }
    result = score_product(product, ScoreThresholds(stock_buffer=2))
    assert result.passed is True


def test_uses_msrp_discount_when_map_missing():
    # sell = 0.95 * 200 = 190; fees = 190*0.1325+0.30 = 25.475; ship 10; landed 100
    # profit = 190 - 25.475 - 10 - 100 = 54.525
    product = {
        "sku": "MSRP",
        "map": 0,
        "msrp": 200.0,
        "landed_cost": 100.0,
        "stock": 10,
    }
    result = score_product(product)
    assert abs(result.sell_price - 190.0) < 1e-9
    assert abs(result.contribution_profit - 54.525) < 1e-9
    assert result.passed is True


def test_uses_dealer_cost_when_landed_missing():
    product = {
        "sku": "DEALER",
        "map": 100.0,
        "dealer_cost": 50.0,
        "stock": 10,
    }
    result = score_product(product)
    assert abs(result.contribution_profit - 26.45) < 1e-9


def test_custom_thresholds():
    product = {
        "sku": "CUSTOM",
        "map": 50.0,
        "landed_cost": 20.0,
        "stock": 1,
    }
    # sell 50; fees 6.925; ship 5; landed 20 → profit 18.075
    th = ScoreThresholds(
        min_contribution_profit_cad=5.0,
        min_contribution_margin=0.20,
        stock_buffer=0,
        ship_est_cad=5.0,
    )
    result = score_product(product, th)
    assert result.passed is True


def test_missing_sell_price_fails():
    product = {"sku": "NOSALE", "map": 0, "msrp": 0, "landed_cost": 10, "stock": 10}
    result = score_product(product)
    assert result.passed is False
    assert "missing_sell_price" in result.reasons


def test_live_dump_formula_sharp_microwave():
    """Regression vs data/rank_summary.json top SKU numbers."""
    product = {
        "sku": "XY45K3YZCNUFODY9HCF5",
        "map": 2599.99,
        "msrp": 2749.99,
        "landed_cost": 1774.19,
        "rebate": 0.0,
        "stock": 3,
    }
    result = score_product(product)
    assert abs(result.contribution_profit - 471.001325) < 1e-4
    assert abs(result.contribution_margin - 0.181155) < 1e-5
    assert result.passed is True

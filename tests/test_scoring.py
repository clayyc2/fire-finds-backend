"""Unit tests for deterministic scoring filters."""

from __future__ import annotations

from firefinds.scoring.filters import (
    ScoreThresholds,
    compute_contribution,
    score_product,
)


def test_compute_contribution_basic():
    profit, margin = compute_contribution(100.0, 80.0, rebate=0.0)
    assert profit == 20.0
    assert abs(margin - 0.20) < 1e-9


def test_compute_contribution_with_rebate():
    profit, margin = compute_contribution(50.0, 40.0, rebate=5.0)
    assert profit == 15.0
    assert abs(margin - 0.30) < 1e-9


def test_compute_contribution_zero_sell_price():
    profit, margin = compute_contribution(0.0, 10.0)
    assert profit == -10.0
    assert margin == 0.0


def test_pass_all_gates():
    # profit = 49.99 - 32 = 17.99 >= 8; margin ~0.36 >= 0.12; stock 10 > 2
    product = {
        "sku": "OK-1",
        "map": 49.99,
        "landed_cost": 32.0,
        "rebate": 0,
        "stock": 10,
    }
    result = score_product(product)
    assert result.passed is True
    assert result.score == result.contribution_profit
    assert abs(result.contribution_profit - 17.99) < 1e-9
    assert result.reasons == ("ok",)


def test_fail_profit_below_threshold():
    # profit = 19.99 - 16.5 = 3.49 < 8
    product = {
        "sku": "LOW-PROFIT",
        "map": 19.99,
        "landed_cost": 16.5,
        "stock": 5,
    }
    result = score_product(product)
    assert result.passed is False
    assert result.score == 0.0
    assert any(r.startswith("profit_below_") for r in result.reasons)


def test_fail_margin_below_threshold():
    # profit = 100 - 92 = 8 >= 8, but margin = 0.08 < 0.12
    product = {
        "sku": "LOW-MARGIN",
        "map": 100.0,
        "landed_cost": 92.0,
        "stock": 10,
    }
    result = score_product(product)
    assert result.passed is False
    assert any(r.startswith("margin_below_") for r in result.reasons)


def test_fail_stock_buffer():
    # stock == buffer fails (must be > buffer)
    product = {
        "sku": "LOW-STOCK",
        "map": 80.0,
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
        "map": 80.0,
        "landed_cost": 50.0,
        "stock": 3,
    }
    result = score_product(product, ScoreThresholds(stock_buffer=2))
    assert result.passed is True


def test_uses_msrp_when_map_missing():
    product = {
        "sku": "MSRP",
        "map": 0,
        "msrp": 100.0,
        "landed_cost": 70.0,
        "stock": 10,
    }
    result = score_product(product)
    assert abs(result.contribution_profit - 30.0) < 1e-9
    assert result.passed is True


def test_uses_dealer_cost_when_landed_missing():
    product = {
        "sku": "DEALER",
        "map": 100.0,
        "dealer_cost": 70.0,
        "stock": 10,
    }
    result = score_product(product)
    assert abs(result.contribution_profit - 30.0) < 1e-9


def test_custom_thresholds():
    product = {
        "sku": "CUSTOM",
        "map": 20.0,
        "landed_cost": 15.0,
        "stock": 1,
    }
    # profit 5, margin 0.25, stock 1
    th = ScoreThresholds(
        min_contribution_profit_cad=5.0,
        min_contribution_margin=0.20,
        stock_buffer=0,
    )
    result = score_product(product, th)
    assert result.passed is True


def test_missing_sell_price_fails():
    product = {"sku": "NOSALE", "map": 0, "msrp": 0, "landed_cost": 10, "stock": 10}
    result = score_product(product)
    assert result.passed is False
    assert "missing_sell_price" in result.reasons

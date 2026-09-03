"""Deterministic contribution / margin / stock filters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class ScoreThresholds:
    min_contribution_profit_cad: float = 8.0
    min_contribution_margin: float = 0.12
    stock_buffer: int = 2
    ebay_fee_rate: float = 0.1325
    ebay_fee_fixed: float = 0.30
    ship_est_cad: float = 10.0
    msrp_discount: float = 0.95


@dataclass(frozen=True)
class ScoreResult:
    contribution_profit: float
    contribution_margin: float
    score: float
    passed: bool
    reasons: tuple[str, ...]
    sell_price: float = 0.0
    fees: float = 0.0

    @property
    def reason(self) -> str:
        return "; ".join(self.reasons) if self.reasons else "ok"


def _f(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _i(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def resolve_sell_price(
    product: Mapping[str, Any],
    *,
    msrp_discount: float = 0.95,
) -> float:
    """Sell = MAP if MAP > 0, else msrp_discount * MSRP."""
    sell = _f(product.get("map"))
    if sell > 0:
        return sell
    msrp = _f(product.get("msrp"))
    if msrp > 0:
        return msrp_discount * msrp
    return 0.0


def compute_contribution(
    sell_price: float,
    landed_cost: float,
    rebate: float = 0.0,
    *,
    ebay_fee_rate: float = 0.1325,
    ebay_fee_fixed: float = 0.30,
    ship_est_cad: float = 10.0,
) -> tuple[float, float, float]:
    """Return (contribution_profit, contribution_margin, fees).

    fees = sell_price * ebay_fee_rate + ebay_fee_fixed
    contribution_profit = sell_price - fees - ship_est_cad - landed_cost + rebate
    contribution_margin = contribution_profit / sell_price (0 if sell_price <= 0)
    """
    sell = float(sell_price)
    fees = sell * float(ebay_fee_rate) + float(ebay_fee_fixed) if sell > 0 else 0.0
    profit = (
        sell
        - fees
        - float(ship_est_cad)
        - float(landed_cost)
        + float(rebate or 0.0)
    )
    if sell > 0:
        margin = profit / sell
    else:
        margin = 0.0
    return profit, margin, fees


def score_product(
    product: Mapping[str, Any],
    thresholds: ScoreThresholds | None = None,
) -> ScoreResult:
    """Apply deterministic gates: profit >= 8 CAD, margin >= 12%, stock > buffer.

    Sell price = MAP else 0.95*MSRP. Landed cost prefers landed_cost, else
    dealer_cost. Fee placeholders: 13.25% + $0.30 and $10 shipping.
    Score is contribution_profit when all gates pass, else 0.
    """
    th = thresholds or ScoreThresholds()
    sell = resolve_sell_price(product, msrp_discount=th.msrp_discount)
    landed = _f(product.get("landed_cost"))
    if landed <= 0:
        landed = _f(product.get("dealer_cost"))
    rebate = _f(product.get("rebate"))
    stock = _i(product.get("stock"))

    profit, margin, fees = compute_contribution(
        sell,
        landed,
        rebate,
        ebay_fee_rate=th.ebay_fee_rate,
        ebay_fee_fixed=th.ebay_fee_fixed,
        ship_est_cad=th.ship_est_cad,
    )
    reasons: list[str] = []

    if sell <= 0:
        reasons.append("missing_sell_price")
    if profit < th.min_contribution_profit_cad:
        reasons.append(f"profit_below_{th.min_contribution_profit_cad}")
    if margin < th.min_contribution_margin:
        reasons.append(f"margin_below_{th.min_contribution_margin}")
    if stock <= th.stock_buffer:
        reasons.append(f"stock_leq_buffer_{th.stock_buffer}")

    passed = len(reasons) == 0
    score = profit if passed else 0.0
    return ScoreResult(
        contribution_profit=profit,
        contribution_margin=margin,
        score=score,
        passed=passed,
        reasons=tuple(reasons) if reasons else ("ok",),
        sell_price=sell,
        fees=fees,
    )

"""Deterministic contribution / margin / stock filters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class ScoreThresholds:
    min_contribution_profit_cad: float = 8.0
    min_contribution_margin: float = 0.12
    stock_buffer: int = 2


@dataclass(frozen=True)
class ScoreResult:
    contribution_profit: float
    contribution_margin: float
    score: float
    passed: bool
    reasons: tuple[str, ...]

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


def compute_contribution(
    sell_price: float,
    landed_cost: float,
    rebate: float = 0.0,
) -> tuple[float, float]:
    """Return (contribution_profit, contribution_margin).

    contribution_profit = sell_price - landed_cost + rebate
    contribution_margin = contribution_profit / sell_price (0 if sell_price <= 0)
    """
    profit = float(sell_price) - float(landed_cost) + float(rebate or 0.0)
    if sell_price and float(sell_price) > 0:
        margin = profit / float(sell_price)
    else:
        margin = 0.0
    return profit, margin


def score_product(
    product: Mapping[str, Any],
    thresholds: ScoreThresholds | None = None,
) -> ScoreResult:
    """Apply deterministic gates: profit >= 8 CAD, margin >= 12%, stock > buffer.

    Sell price prefers MAP, then MSRP. Landed cost prefers landed_cost, else
    dealer_cost. Score is contribution_profit when all gates pass, else 0.
    """
    th = thresholds or ScoreThresholds()
    sell = _f(product.get("map"))
    if sell <= 0:
        sell = _f(product.get("msrp"))
    landed = _f(product.get("landed_cost"))
    if landed <= 0:
        landed = _f(product.get("dealer_cost"))
    rebate = _f(product.get("rebate"))
    stock = _i(product.get("stock"))

    profit, margin = compute_contribution(sell, landed, rebate)
    reasons: list[str] = []

    if sell <= 0:
        reasons.append("missing_sell_price")
    if landed <= 0 and "missing_sell_price" not in reasons:
        # still allow scoring numbers, but flag if both missing meaningfully
        pass
    if profit < th.min_contribution_profit_cad:
        reasons.append(
            f"profit_below_{th.min_contribution_profit_cad}"
        )
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
    )

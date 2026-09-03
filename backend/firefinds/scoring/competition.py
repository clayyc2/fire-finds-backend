"""Competition pricing, MAP gates, sales probability, composite rank."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from firefinds.clients.ebay import CompetitionSnapshot
from firefinds.config import Settings
from firefinds.scoring.filters import compute_contribution


@dataclass(frozen=True)
class CompetitionMarginResult:
    sell_comp: float
    fees: float
    contribution_profit: float
    contribution_margin: float
    listable_pass: bool
    reasons: tuple[str, ...]
    competition_found: bool
    below_map: bool
    opportunity_only: bool
    sales_probability: float
    expected_monthly_units: float
    expected_monthly_contribution_profit: float
    rank_score: float
    provisional_public_ebay: bool
    needs_official_ebay_validation: bool
    shipping_status: str = "UNRESOLVED"
    shipping_cost_cad: float | None = None
    final_profitability: bool = False

    @property
    def reason(self) -> str:
        return "; ".join(self.reasons) if self.reasons else "ok"


def resolve_compete_sell_price(
    product: Mapping[str, Any],
    snapshot: CompetitionSnapshot,
    *,
    strategy: str = "min_map_median",
    median_factor: float = 0.98,
) -> float:
    """Competition sell price before MAP floor is applied."""
    map_price = float(product.get("map") or 0.0)
    median = snapshot.median_price
    lowest = snapshot.lowest_price
    factor = float(median_factor)

    if strategy == "lowest":
        return float(lowest) if lowest and lowest > 0 else 0.0
    if strategy == "median":
        return float(median) * factor if median and median > 0 else 0.0

    candidates: list[float] = []
    if median and median > 0:
        candidates.append(float(median) * factor)
    if map_price > 0:
        candidates.append(map_price)
    if not candidates and lowest and lowest > 0:
        candidates.append(float(lowest))
    return min(candidates) if candidates else 0.0


def apply_map_floor(sell: float, map_price: float) -> tuple[float, bool]:
    """Never price below MAP. Returns (sell, below_map_attempt)."""
    if map_price > 0 and sell > 0 and sell < map_price:
        return map_price, True
    if map_price > 0 and sell <= 0:
        return map_price, False
    return sell, False


def estimate_sales_probability(
    product: Mapping[str, Any],
    snapshot: CompetitionSnapshot,
    *,
    return_risk: float = 0.0,
) -> float:
    """Heuristic 0..1 sales probability from competition depth + stock."""
    count = max(0, int(snapshot.item_count or 0))
    # Sweet spot: some demand signal but not hyper-saturated.
    if count <= 0:
        base = 0.15  # unknown / provisional
    elif count <= 5:
        base = 0.55
    elif count <= 20:
        base = 0.70
    elif count <= 50:
        base = 0.50
    else:
        base = 0.35

    stock = int(product.get("stock") or 0)
    if stock >= 10:
        base += 0.08
    elif stock >= 5:
        base += 0.04
    elif stock <= 2:
        base -= 0.10

    if snapshot.found and snapshot.median_price and product.get("map"):
        try:
            map_p = float(product["map"])
            if map_p > 0 and snapshot.lowest_price and snapshot.lowest_price < map_p * 0.9:
                # Market already under MAP — harder to win while respecting MAP
                base -= 0.15
        except (TypeError, ValueError):
            pass

    base -= min(0.4, float(return_risk) * 0.5)
    return max(0.01, min(0.95, round(base, 4)))


def evaluate_listable(
    product: Mapping[str, Any],
    snapshot: CompetitionSnapshot,
    settings: Settings,
    *,
    provisional_public_ebay: bool = False,
    needs_official_ebay_validation: bool = False,
    return_risk: float = 0.0,
    shipping_status: str = "UNRESOLVED",
    shipping_cost_cad: float | None = None,
) -> CompetitionMarginResult:
    """Recompute margin at competition sell (MAP-floored) and apply gates.

    final_profitability / listable_pass require shipping_status=RESOLVED with a
    real quote. Unresolved shipping hard-fails final listable classification.
    """
    rebate = float(product.get("rebate") or 0.0)
    stock = int(product.get("stock") or 0)
    map_price = float(product.get("map") or 0.0)
    opportunity_only = bool(product.get("opportunity_only"))
    dealer = float(product.get("dealer_cost") or 0.0)
    net = float(product.get("net_cost") or 0.0)
    if net <= 0:
        net = max(0.0, dealer - rebate)

    raw_sell = resolve_compete_sell_price(
        product,
        snapshot,
        strategy=settings.ebay_compete_strategy,
        median_factor=settings.ebay_compete_median_factor,
    )
    sell, below_map_attempt = apply_map_floor(raw_sell, map_price)

    ship_resolved = (
        str(shipping_status).upper() == "RESOLVED"
        and shipping_cost_cad is not None
    )
    if ship_resolved:
        landed = net  # shipping applied separately via ship_est_cad
        ship = float(shipping_cost_cad)
    else:
        landed = net
        ship = 0.0  # do NOT invent a placeholder for final math

    profit, margin, fees = compute_contribution(
        sell,
        landed,
        rebate,
        ebay_fee_rate=settings.ebay_fee_rate,
        ebay_fee_fixed=settings.ebay_fee_fixed,
        ship_est_cad=ship,
    )

    reasons: list[str] = []
    found = snapshot.found
    if not ship_resolved:
        reasons.append("shipping_unresolved")
    if opportunity_only:
        reasons.append("opportunity_only_channel_restricted")
    if not found and needs_official_ebay_validation and not provisional_public_ebay:
        reasons.append("awaiting_official_ebay_validation")
    if not found and not provisional_public_ebay and not needs_official_ebay_validation:
        reasons.append("no_competition")
    # Provisional path may proceed without official competition if other gates pass
    # but still flagged needs_official_ebay_validation.
    if sell <= 0:
        reasons.append("missing_sell_comp")
    if map_price > 0 and sell + 1e-9 < map_price:
        reasons.append("sell_below_map")
    if below_map_attempt and raw_sell > 0 and raw_sell < map_price:
        # After floor we sell at MAP; note market was under MAP
        pass
    if profit < settings.min_contribution_profit_cad:
        reasons.append(f"profit_below_{settings.min_contribution_profit_cad}")
    if margin < settings.min_contribution_margin:
        reasons.append(f"margin_below_{settings.min_contribution_margin}")
    if stock <= settings.stock_buffer:
        reasons.append(f"stock_leq_buffer_{settings.stock_buffer}")
    min_listings = settings.ebay_min_comp_listings
    if found and snapshot.item_count < min_listings:
        reasons.append(f"comp_listings_below_{min_listings}")

    # Soft: provisional without competition — allow pass only if MAP-based
    # profitability holds and we explicitly allow provisional ranking.
    if (
        not found
        and provisional_public_ebay
        and "no_competition" in reasons
    ):
        reasons = [r for r in reasons if r != "no_competition"]
    if (
        not found
        and needs_official_ebay_validation
        and "awaiting_official_ebay_validation" in reasons
        and settings.allow_provisional_listable
    ):
        reasons = [
            r for r in reasons if r != "awaiting_official_ebay_validation"
        ]

    sales_p = estimate_sales_probability(
        product, snapshot, return_risk=return_risk
    )
    # Baseline monthly attempts proxy
    monthly_units = round(sales_p * float(settings.monthly_demand_baseline), 4)
    expected_monthly = round(profit * monthly_units, 4)
    rank_score = round(expected_monthly * sales_p, 6)

    listable_pass = len(reasons) == 0
    final_profitability = listable_pass and ship_resolved
    # Rank score is 0 when shipping unresolved (not finally profitable).
    if not ship_resolved:
        rank_score = 0.0
        expected_monthly = 0.0
    return CompetitionMarginResult(
        sell_comp=sell,
        fees=fees,
        contribution_profit=profit,
        contribution_margin=margin,
        listable_pass=listable_pass,
        reasons=tuple(reasons) if reasons else ("ok",),
        competition_found=found,
        below_map=below_map_attempt,
        opportunity_only=opportunity_only,
        sales_probability=sales_p,
        expected_monthly_units=monthly_units if ship_resolved else 0.0,
        expected_monthly_contribution_profit=expected_monthly,
        rank_score=rank_score,
        provisional_public_ebay=provisional_public_ebay,
        needs_official_ebay_validation=needs_official_ebay_validation,
        shipping_status="RESOLVED" if ship_resolved else "UNRESOLVED",
        shipping_cost_cad=float(shipping_cost_cad) if ship_resolved else None,
        final_profitability=final_profitability,
    )

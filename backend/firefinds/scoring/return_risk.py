"""Return-risk / category exclusion heuristics."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


DEFAULT_DENY_KEYWORDS = (
    "lithium",
    "hazmat",
    "flammable",
    "pesticide",
    "ammunition",
    "firearm",
    "refrigerator",
    "fridge",
    "freezer",
    "washing machine",
    "washer",
    "dryer",
    "dishwasher",
    "mattress",
    "treadmill",
)

DEFAULT_DENY_CATEGORIES = (
    "hazmat",
    "oversized appliances",
    "major appliances",
)


@dataclass(frozen=True)
class ReturnRiskResult:
    excluded: bool
    reasons: tuple[str, ...]
    risk_score: float  # 0..1 higher = riskier


def evaluate_return_risk(
    product: Mapping[str, Any],
    *,
    deny_keywords: Sequence[str] = DEFAULT_DENY_KEYWORDS,
    deny_categories: Sequence[str] = DEFAULT_DENY_CATEGORIES,
    heavy_weight_lb: float = 30.0,
    high_msrp_cad: float = 1500.0,
) -> ReturnRiskResult:
    reasons: list[str] = []
    risk = 0.0
    title = " ".join(
        str(product.get(k) or "")
        for k in ("title", "RandmarTitle", "category", "product_type", "Category")
    ).lower()
    category = str(
        product.get("category")
        or product.get("Category")
        or product.get("product_type")
        or product.get("ProductType")
        or ""
    ).lower()

    for kw in deny_keywords:
        if kw.lower() in title or kw.lower() in category:
            reasons.append(f"deny_keyword:{kw}")
            risk = max(risk, 0.9)

    for cat in deny_categories:
        if cat.lower() in category:
            reasons.append(f"deny_category:{cat}")
            risk = max(risk, 0.95)

    try:
        weight = float(product.get("unit_weight") or product.get("UnitWeight") or 0)
    except (TypeError, ValueError):
        weight = 0.0
    if weight >= heavy_weight_lb:
        reasons.append(f"heavy_weight_{weight}")
        risk = max(risk, 0.7)

    try:
        msrp = float(product.get("msrp") or product.get("MSRP") or 0)
    except (TypeError, ValueError):
        msrp = 0.0
    # High-MSRP small accessories often have painful returns (heuristic).
    mpn = str(product.get("mpn") or product.get("MPN") or "").lower()
    if msrp >= high_msrp_cad and re.search(r"(case|cover|cable|charger|sleeve)", title):
        reasons.append("high_msrp_accessory")
        risk = max(risk, 0.6)

    return ReturnRiskResult(
        excluded=len(reasons) > 0 and risk >= 0.6,
        reasons=tuple(reasons),
        risk_score=risk,
    )

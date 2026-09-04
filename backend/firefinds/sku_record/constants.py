"""Shared SKU measurable-outcome enums and field groups."""

from __future__ import annotations

PIPELINE_RANDMAR_FIRST = "RANDMAR_FIRST"
PIPELINE_EBAY_DEMAND_FIRST = "EBAY_DEMAND_FIRST"
PIPELINE_SOURCES = frozenset({PIPELINE_RANDMAR_FIRST, PIPELINE_EBAY_DEMAND_FIRST})

MATCH_A_EXACT = "A_EXACT"
MATCH_B_VARIANT = "B_VARIANT"
MATCH_C_SUBSTITUTE = "C_SUBSTITUTE"
MATCH_CONFIDENCE_VALUES = frozenset(
    {MATCH_A_EXACT, MATCH_B_VARIANT, MATCH_C_SUBSTITUTE}
)

CREATIVE_ORIGINAL_SUPPLIER = "ORIGINAL_SUPPLIER"
CREATIVE_AI_ENHANCED = "AI_ENHANCED"
CREATIVE_VARIANTS = frozenset(
    {CREATIVE_ORIGINAL_SUPPLIER, CREATIVE_AI_ENHANCED}
)

LISTING_SIMULATED = "SIMULATED_LISTED"
ORDER_SIMULATED = "SIMULATED_ORDER"

# Research department writes
RESEARCH_METRIC_KEYS = (
    "pipeline_source",
    "match_confidence",
    "demand_evidence_refs",
    "competition_snapshot_flags",
)

# Creative department writes
CREATIVE_METRIC_KEYS = (
    "creative_version_id",
    "creative_variant",
    "asset_paths",
    "ab_assignment",
)

# Marketplace performance (nullable until live)
MARKETPLACE_METRIC_KEYS = (
    "impressions",
    "ctr",
    "conversion_rate",
    "sales_units",
    "contribution_profit_realized",
    "cancellations",
    "returns",
    "time_to_first_sale",
    "sell_through",
)

# Learning / A/B linkage
LEARNING_METRIC_KEYS = ("comparison_cohort_id",)

# Simulation / ops status (dry-run and later live)
STATUS_METRIC_KEYS = (
    "listing_status",
    "order_status",
)

ALL_MEASURABLE_KEYS = (
    RESEARCH_METRIC_KEYS
    + CREATIVE_METRIC_KEYS
    + MARKETPLACE_METRIC_KEYS
    + LEARNING_METRIC_KEYS
    + STATUS_METRIC_KEYS
)

# JSON-encoded text columns on products
JSON_METRIC_KEYS = frozenset(
    {"demand_evidence_refs", "competition_snapshot_flags", "asset_paths"}
)

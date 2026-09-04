"""Dual-pipeline tagging helpers and A/B comparison metric placeholders."""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping

PIPELINE_RANDMAR_FIRST = "RANDMAR_FIRST"
PIPELINE_EBAY_DEMAND_FIRST = "EBAY_DEMAND_FIRST"

COHORT_SAFE_NATIONWIDE = "SAFE_NATIONWIDE"
COHORT_DESTINATION_SENSITIVE = "DESTINATION_SENSITIVE"
COHORT_QUARANTINE_UNRESOLVED = "QUARANTINE_UNRESOLVED"
COHORT_MAP_BLOCKED = "MAP_BLOCKED"
COHORT_CHANNEL_RESTRICTED = "CHANNEL_RESTRICTED"
COHORT_NEEDS_MANUAL_REVIEW = "NEEDS_MANUAL_CHANNEL_REVIEW"

AB_METRIC_KEYS = (
    "sell_through",
    "time_to_first_sale",
    "contribution_profit_realized",
    "cancellations",
    "returns",
    "impressions",
    "ctr",
    "conversion_rate",
    "sales_units",
)


def comparison_cohort_id(
    *,
    pipeline_source: str,
    cohort: str,
    snapshot_id: str,
) -> str:
    """Stable id for later A/B grouping across pipelines."""
    return f"{snapshot_id}|{pipeline_source}|{cohort}"


def ab_metric_placeholders() -> dict[str, None]:
    """Empty metric columns ready until live sell-through data exists."""
    return {k: None for k in AB_METRIC_KEYS}


def tag_candidate(
    row: Mapping[str, Any] | MutableMapping[str, Any],
    *,
    pipeline_source: str,
    cohort: str,
    snapshot_id: str,
) -> dict[str, Any]:
    """Attach dual-pipeline tags + empty A/B metrics to a candidate row."""
    out = dict(row)
    out["pipeline_source"] = pipeline_source
    out["cohort"] = cohort
    out["comparison_cohort_id"] = comparison_cohort_id(
        pipeline_source=pipeline_source,
        cohort=cohort,
        snapshot_id=snapshot_id,
    )
    for k, v in ab_metric_placeholders().items():
        out.setdefault(k, v)
    return out

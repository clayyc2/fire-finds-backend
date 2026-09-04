"""Shared SKU measurable outcomes schema + helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from firefinds.config import Settings
from firefinds.db.schema import init_db
from firefinds.sku_record.constants import (
    ALL_MEASURABLE_KEYS,
    CREATIVE_ORIGINAL_SUPPLIER,
    MATCH_A_EXACT,
    PIPELINE_RANDMAR_FIRST,
)
from firefinds.sku_record.metrics import (
    export_learning_comparison,
    get_sku_record,
    upsert_sku_metrics,
)
from firefinds.services import ingest_stub


def test_schema_has_measurable_columns(settings: Settings):
    conn = init_db(settings.db_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(products)").fetchall()}
    expected = {
        "pipeline_source",
        "match_confidence",
        "demand_evidence_refs",
        "competition_snapshot_flags",
        "creative_version_id",
        "creative_variant",
        "asset_paths",
        "ab_assignment",
        "impressions",
        "ctr",
        "conversion_rate",
        "sales_units",
        "contribution_profit_realized",
        "cancellations",
        "returns",
        "time_to_first_sale",
        "sell_through",
        "comparison_cohort_id",
        "listing_status",
        "order_status",
    }
    assert expected <= cols
    cc = {r[1] for r in conn.execute("PRAGMA table_info(candidate_cohorts)").fetchall()}
    assert {"impressions", "ctr", "match_confidence", "creative_variant"} <= cc
    conn.close()


def test_upsert_and_get_metrics(settings: Settings):
    ingest_stub(settings)
    sku = "FF-STUB-001"
    record = upsert_sku_metrics(
        sku,
        {
            "pipeline_source": PIPELINE_RANDMAR_FIRST,
            "match_confidence": MATCH_A_EXACT,
            "demand_evidence_refs": {"sources": ["test"], "n": 1},
            "competition_snapshot_flags": {"provisional_public_ebay": True},
            "creative_version_id": "cv-test-1",
            "creative_variant": CREATIVE_ORIGINAL_SUPPLIER,
            "asset_paths": ["/tmp/a.json"],
            "ab_assignment": "A",
            "comparison_cohort_id": "snap|RANDMAR_FIRST|SAFE_NATIONWIDE",
            # marketplace stays null-ish except one value for round-trip
            "impressions": None,
            "ctr": None,
        },
        settings=settings,
        source="test",
    )
    m = record["metrics"]
    assert m["pipeline_source"] == PIPELINE_RANDMAR_FIRST
    assert m["match_confidence"] == MATCH_A_EXACT
    assert m["demand_evidence_refs"]["sources"] == ["test"]
    assert m["competition_snapshot_flags"]["provisional_public_ebay"] is True
    assert m["creative_variant"] == CREATIVE_ORIGINAL_SUPPLIER
    assert m["asset_paths"] == ["/tmp/a.json"]
    assert m["comparison_cohort_id"].endswith("SAFE_NATIONWIDE")
    assert m["impressions"] is None
    assert set(ALL_MEASURABLE_KEYS) <= set(m.keys())

    got = get_sku_record(sku, settings=settings)
    assert got["sku"] == sku
    assert got["metrics"]["creative_version_id"] == "cv-test-1"


def test_upsert_rejects_unknown_and_bad_enums(settings: Settings):
    ingest_stub(settings)
    with pytest.raises(ValueError, match="unknown measurable"):
        upsert_sku_metrics("FF-STUB-001", {"not_a_field": 1}, settings=settings)
    with pytest.raises(ValueError, match="match_confidence"):
        upsert_sku_metrics(
            "FF-STUB-001",
            {"match_confidence": "FUZZY"},
            settings=settings,
        )
    with pytest.raises(ValueError, match="pipeline_source"):
        upsert_sku_metrics(
            "FF-STUB-001",
            {"pipeline_source": "OTHER"},
            settings=settings,
        )


def test_export_learning_comparison(settings: Settings, tmp_path: Path):
    ingest_stub(settings)
    upsert_sku_metrics(
        "FF-STUB-001",
        {
            "pipeline_source": PIPELINE_RANDMAR_FIRST,
            "match_confidence": MATCH_A_EXACT,
            "comparison_cohort_id": "t1|RANDMAR_FIRST|SAFE_NATIONWIDE",
            "creative_variant": CREATIVE_ORIGINAL_SUPPLIER,
            "ab_assignment": "A",
        },
        settings=settings,
    )
    out = tmp_path / "learn.json"
    payload = export_learning_comparison(
        settings=settings,
        comparison_cohort_id="t1|RANDMAR_FIRST|SAFE_NATIONWIDE",
        export_path=out,
    )
    assert payload["count"] == 1
    assert out.is_file()
    loaded = json.loads(out.read_text())
    assert loaded["rows"][0]["sku"] == "FF-STUB-001"
    assert loaded["rows"][0]["match_confidence"] == MATCH_A_EXACT

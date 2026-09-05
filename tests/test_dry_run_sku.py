"""Simulated one-SKU E2E dry-run (no live publish / no supplier Process)."""

from __future__ import annotations

import json
from pathlib import Path

from firefinds.config import Settings
from firefinds.db.schema import init_db
from firefinds.sku_record.constants import (
    LISTING_SIMULATED,
    ORDER_SIMULATED,
    PIPELINE_RANDMAR_FIRST,
)
from firefinds.sku_record.dry_run import recheck_backend_gates, run_dry_run_sku
from firefinds.services import ingest_stub, score_all
from firefinds.cli.main import main


def _seed_listable(settings: Settings) -> str:
    ingest_stub(settings)
    score_all(settings)
    conn = init_db(settings.db_path)
    row = conn.execute(
        "SELECT sku, map, stock, dealer_cost, rebate FROM products "
        "WHERE score_pass=1 ORDER BY score DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    sku = row["sku"]
    # Make finally-listable fields look like a SAFE_NATIONWIDE survivor
    conn.execute(
        """
        UPDATE products SET
            shipping_status='RESOLVED',
            ship_p75=12.0,
            listable_pass=1,
            listable_profit=40.0,
            listable_margin=0.20,
            sell_comp=?,
            map=?,
            opportunity_only=0,
            provisional_public_ebay=1,
            needs_official_ebay_validation=1,
            cohort='SAFE_NATIONWIDE',
            pipeline_source=?,
            comparison_cohort_id='testsnap|RANDMAR_FIRST|SAFE_NATIONWIDE',
            fails_expensive_destinations=0
        WHERE sku=?
        """,
        (float(row["map"] or 100), float(row["map"] or 100), PIPELINE_RANDMAR_FIRST, sku),
    )
    conn.execute("DELETE FROM ranked_queue")
    conn.execute(
        """
        INSERT INTO ranked_queue (
            rank, sku, rank_score, expected_monthly_contribution_profit,
            sales_probability, sell_comp, listable_profit, listable_margin,
            map, stock, provisional_public_ebay, needs_official_ebay_validation,
            reason, ship_p75, shipping_status, fails_expensive_destinations,
            failed_expensive_destinations, pipeline_source, cohort,
            comparison_cohort_id
        ) VALUES (1, ?, 10, 50, 0.5, ?, 40, 0.20, ?, ?, 1, 1, 'ok', 12.0,
                  'RESOLVED', 0, '[]', ?, 'SAFE_NATIONWIDE',
                  'testsnap|RANDMAR_FIRST|SAFE_NATIONWIDE')
        """,
        (sku, float(row["map"] or 100), float(row["map"] or 100), row["stock"],
         PIPELINE_RANDMAR_FIRST),
    )
    conn.execute(
        """
        INSERT INTO candidate_cohorts (
            sku, pipeline_source, cohort, comparison_cohort_id, snapshot_id,
            rank, fails_expensive_destinations, listable_profit, listable_margin,
            sell_comp, map, ship_p75, shipping_status
        ) VALUES (?, ?, 'SAFE_NATIONWIDE',
                  'testsnap|RANDMAR_FIRST|SAFE_NATIONWIDE', 'testsnap',
                  1, 0, 40.0, 0.20, ?, ?, 12.0, 'RESOLVED')
        """,
        (
            sku,
            PIPELINE_RANDMAR_FIRST,
            float(row["map"] or 100),
            float(row["map"] or 100),
        ),
    )
    conn.commit()
    conn.close()
    return sku


def test_recheck_backend_gates_pass(settings: Settings):
    sku = _seed_listable(settings)
    conn = init_db(settings.db_path)
    product = dict(conn.execute("SELECT * FROM products WHERE sku=?", (sku,)).fetchone())
    conn.close()
    product.update(channel_allowed=True, channel_evidence="test fixture permission")
    result = recheck_backend_gates(product, settings=settings)
    assert result["pass"] is True
    assert result["checks"]["shipping_resolved"]["pass"] is True
    assert result["checks"]["profit_ge_8"]["pass"] is True
    assert result["checks"]["margin_ge_12pct"]["pass"] is True
    assert result["checks"]["map_ok"]["pass"] is True
    assert result["checks"]["channel_ok"]["pass"] is True


def test_legacy_listable_flags_without_permission_hold_e2e(settings: Settings, tmp_path: Path):
    sku = _seed_listable(settings)
    report_dir = tmp_path / "dry_runs"
    report = run_dry_run_sku(
        sku=sku,
        settings=settings,
        snapshot_id="testsnap",
        include_ai_twin=True,
        report_dir=report_dir,
    )
    assert report["sku"] == sku
    assert report["dry_run"] is True
    assert report["live_publish"] is False
    assert report["supplier_order_api_called"] is False
    assert report["backend_gates"]["pass"] is False
    assert report["backend_gates"]["checks"]["channel_ok"]["pass"] is False
    assert report["listing_status"] is None
    assert report["order_status"] is None
    stage_names = [s["stage"] for s in report["stages"]]
    assert stage_names == [
        "research",
        "creative",
        "backend_gates",
        "operations",
    ]
    assert Path(report["report_path"]).is_file()
    metrics = report["sku_record_metrics"]
    assert metrics["pipeline_source"] == PIPELINE_RANDMAR_FIRST
    assert metrics["match_confidence"] == "A_EXACT"
    assert metrics["creative_variant"] == "ORIGINAL_SUPPLIER"
    assert metrics["listing_status"] != LISTING_SIMULATED
    assert metrics["order_status"] != ORDER_SIMULATED
    assert metrics["ab_assignment"] == "A|B"
    # Drafts written
    creative = next(s for s in report["stages"] if s["stage"] == "creative")
    assert Path(creative["draft_path"]).is_file()
    assert Path(creative["ai_twin_path"]).is_file()
    # Action log has dry-run entries
    lines = settings.actions_jsonl.read_text(encoding="utf-8").strip().splitlines()
    actions = {json.loads(line)["action"] for line in lines}
    assert "dry_run_research" in actions
    assert "dry_run_listing" not in actions
    assert "dry_run_order" not in actions
    assert "dry_run_complete" in actions


def test_cli_dry_run_sku(monkeypatch, tmp_path: Path, settings: Settings):
    sku = _seed_listable(settings)
    monkeypatch.setenv("FIREFINDS_DB_PATH", str(settings.db_path))
    monkeypatch.setenv("FIREFINDS_ACTIONS_JSONL", str(settings.actions_jsonl))
    monkeypatch.setenv("LIVE_LISTINGS_ENABLED", "false")
    monkeypatch.setenv("SUPPLIER_ORDERS_ENABLED", "false")
    monkeypatch.setenv("EBAY_SANDBOX_PUBLISH_ENABLED", "false")
    rc = main(["dry-run-sku", "--sku", sku, "--snapshot-id", "testsnap"])
    assert rc == 1  # Legacy listable flags lack explicit channel permission.

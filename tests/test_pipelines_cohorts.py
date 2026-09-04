"""Snapshot freeze, cohort split, authorization, EBAY_DEMAND_FIRST."""

from __future__ import annotations

import json
from pathlib import Path

from firefinds.config import Settings
from firefinds.db.schema import init_db
from firefinds.discovery.ebay_demand import (
    DemandSignal,
    ProvisionalPublicDemandProvider,
    discover_ebay_demand_first,
    match_signal_to_catalog,
)
from firefinds.pipelines.authorize import authorize_and_draft_survivors, authorize_sku
from firefinds.pipelines.cohorts import split_randmar_cohorts
from firefinds.pipelines.snapshot import freeze_shipping_snapshot
from firefinds.pipelines.tags import (
    COHORT_DESTINATION_SENSITIVE,
    COHORT_QUARANTINE_UNRESOLVED,
    COHORT_SAFE_NATIONWIDE,
    PIPELINE_EBAY_DEMAND_FIRST,
    PIPELINE_RANDMAR_FIRST,
)
from firefinds.services import ingest_stub


def _seed_ranked(settings: Settings) -> None:
    ingest_stub(settings)
    conn = init_db(settings.db_path)
    # Mark two stubs as finally profitable in ranked_queue
    rows = conn.execute(
        "SELECT sku, map, stock FROM products WHERE score_pass=1 ORDER BY sku"
    ).fetchall()
    assert len(rows) >= 2
    conn.execute("DELETE FROM ranked_queue")
    # SAFE
    conn.execute(
        """
        INSERT INTO ranked_queue (
            rank, sku, rank_score, expected_monthly_contribution_profit,
            sales_probability, sell_comp, listable_profit, listable_margin,
            map, stock, provisional_public_ebay, needs_official_ebay_validation,
            reason, ship_p75, shipping_status, fails_expensive_destinations,
            failed_expensive_destinations
        ) VALUES (1, ?, 10, 50, 0.5, ?, 40, 0.2, ?, ?, 1, 1, 'ok', 12.0,
                  'RESOLVED', 0, '[]')
        """,
        (rows[0]["sku"], float(rows[0]["map"] or 100), float(rows[0]["map"] or 100), rows[0]["stock"]),
    )
    # SENSITIVE
    conn.execute(
        """
        INSERT INTO ranked_queue (
            rank, sku, rank_score, expected_monthly_contribution_profit,
            sales_probability, sell_comp, listable_profit, listable_margin,
            map, stock, provisional_public_ebay, needs_official_ebay_validation,
            reason, ship_p75, shipping_status, fails_expensive_destinations,
            failed_expensive_destinations
        ) VALUES (2, ?, 8, 40, 0.4, ?, 30, 0.18, ?, ?, 1, 1, 'ok', 25.0,
                  'RESOLVED', 1, '["Halifax"]')
        """,
        (rows[1]["sku"], float(rows[1]["map"] or 100), float(rows[1]["map"] or 100), rows[1]["stock"]),
    )
    # Unresolved quarantine seed
    conn.execute(
        """
        UPDATE products SET shipping_status='UNRESOLVED', listable_pass=0
        WHERE sku=?
        """,
        (rows[0]["sku"],),  # also leave one unresolved separate
    )
    # Ensure at least one unresolved that is NOT in ranked_queue
    extra = conn.execute(
        "SELECT sku FROM products WHERE score_pass=0 OR sku NOT IN "
        "(SELECT sku FROM ranked_queue) LIMIT 1"
    ).fetchone()
    if extra:
        conn.execute(
            "UPDATE products SET shipping_status='UNRESOLVED' WHERE sku=?",
            (extra["sku"],),
        )
    # Fix: first ranked should be RESOLVED for cohort math
    conn.execute(
        "UPDATE products SET shipping_status='RESOLVED', listable_pass=1, "
        "fails_expensive_destinations=0 WHERE sku=?",
        (rows[0]["sku"],),
    )
    conn.execute(
        "UPDATE products SET shipping_status='RESOLVED', listable_pass=1, "
        "fails_expensive_destinations=1 WHERE sku=?",
        (rows[1]["sku"],),
    )
    # Dedicated unresolved SKU not in ranked
    other = [r for r in rows[2:]] if len(rows) > 2 else []
    if not other:
        conn.execute(
            """
            INSERT INTO products (sku, map, msrp, dealer_cost, stock, score_pass,
                                  eligible, shipping_status, listable_pass)
            VALUES ('FF-UNRES-1', 50, 60, 20, 10, 0, 0, 'UNRESOLVED', 0)
            """
        )
    else:
        conn.execute(
            "UPDATE products SET shipping_status='UNRESOLVED', listable_pass=0 WHERE sku=?",
            (other[0]["sku"],),
        )
    conn.commit()
    # Write progress + ranked_queue export for freeze
    data = Path(settings.db_path).parent
    (data / "shipping_quote_progress.json").write_text(
        json.dumps(
            {
                "resolved_skus": 2,
                "unresolved_skus": 1,
                "complete": True,
                "updated_at": "2026-09-03T23:44:41+00:00",
            }
        ),
        encoding="utf-8",
    )
    (data / "ranked_queue.json").write_text(
        json.dumps({"summary": {"listable_pass_count": 2}, "queue": []}),
        encoding="utf-8",
    )


def test_authorize_map_floor_and_opportunity():
    auth = authorize_sku({"map": 100, "sell_comp": 80, "opportunity_only": False})
    assert auth["map_ok"] is True
    assert auth["sell_price"] == 100
    assert "market_under_map_floored" in auth["authorization_flags"]
    auth2 = authorize_sku({"map": 50, "sell_comp": 60, "opportunity_only": True})
    assert auth2["channel_ok"] is False
    assert auth2["needs_manual_channel_review"] is True


def test_freeze_split_authorize(settings: Settings):
    _seed_ranked(settings)
    meta = freeze_shipping_snapshot(
        settings=settings, snapshot_id="20260903_1744", git_head="deadbeef"
    )
    snap = Path(meta["snapshot_dir"])
    assert snap.is_dir()
    assert (snap / "freeze_metadata.json").is_file()
    assert meta["pipeline_source"] == PIPELINE_RANDMAR_FIRST
    assert meta["git_head"] == "deadbeef"

    split = split_randmar_cohorts(settings=settings, snapshot_id="20260903_1744")
    assert split["summary"]["safe_nationwide"] == 1
    assert split["summary"]["destination_sensitive"] == 1
    assert split["summary"]["quarantine_unresolved"] >= 1
    assert all(r["cohort"] == COHORT_SAFE_NATIONWIDE for r in split["safe"])
    assert all(r["cohort"] == COHORT_DESTINATION_SENSITIVE for r in split["sensitive"])
    assert all(
        r["pipeline_source"] == PIPELINE_RANDMAR_FIRST for r in split["safe"]
    )
    assert all("comparison_cohort_id" in r for r in split["quarantine"])

    drafts = authorize_and_draft_survivors(
        settings=settings, snapshot_id="20260903_1744"
    )
    assert drafts["summary"]["drafts_written"] == 2
    out = Path(drafts["summary"]["drafts_dir"])
    safe_files = list((out / "safe_nationwide").glob("*.json"))
    sens_files = list((out / "destination_sensitive").glob("*.json"))
    assert len(safe_files) == 1
    assert len(sens_files) == 1
    # Separated queue dirs from split
    cohort_root = Path(settings.db_path).parent / "cohorts" / "20260903_1744"
    assert (cohort_root / "randmar_first" / "safe_nationwide" / "queue.json").is_file()
    assert (cohort_root / "randmar_first" / "destination_sensitive" / "queue.json").is_file()
    assert (cohort_root / "quarantine_unresolved" / "queue.json").is_file()
    assert (cohort_root / "READY_TO_LIST_QUEUES.json").is_file()
    sample = json.loads(safe_files[0].read_text())
    assert sample["publish"] is False
    assert sample["authorization"]["map_ok"] is True
    assert "pipeline_source" in sample
    assert sample.get("cohort") == COHORT_SAFE_NATIONWIDE


def test_match_rules_exact_upc_and_mpn():
    catalog = [
        {
            "sku": "A",
            "upc": "012345678905",
            "upc_norm": "012345678905",
            "upc_valid": 1,
            "mpn": "XYZ-1",
            "mpn_norm": "XYZ-1",
            "manufacturer": "Acme",
            "stock": 5,
            "model": "M1",
        },
        {
            "sku": "B",
            "upc": None,
            "mpn": "XYZ-1",
            "mpn_norm": "XYZ-1",
            "manufacturer": "Acme",
            "stock": 9,
            "model": "M2",
        },
    ]
    # Valid checksum UPC for test — use normalize that may flag invalid; match still exact
    sig = DemandSignal(
        query="upc",
        query_type="upc",
        upc="012345678905",
        sold_count=3,
        repeated_demand=True,
    )
    m = match_signal_to_catalog(sig, catalog)
    assert m.match_rule == "exact_upc"
    assert m.sku == "A"

    sig2 = DemandSignal(
        query="mpn",
        query_type="mpn",
        mpn="XYZ-1",
        manufacturer="Acme",
        model="M2",
        sold_count=4,
        repeated_demand=True,
    )
    m2 = match_signal_to_catalog(sig2, catalog)
    # ambiguous mpn+mfr with model → controlled_variant on B
    assert m2.match_rule == "controlled_variant"
    assert m2.sku == "B"


def test_ebay_demand_first_with_injected_signals(settings: Settings):
    ingest_stub(settings)
    conn = init_db(settings.db_path)
    row = conn.execute(
        "SELECT * FROM products WHERE score_pass=1 ORDER BY sku LIMIT 1"
    ).fetchone()
    assert row is not None
    conn.execute(
        """
        UPDATE products SET shipping_status='RESOLVED', ship_p75=10.0,
               ship_est=10.0, fails_expensive_destinations=0,
               listable_pass=1, net_cost=IFNULL(dealer_cost,0)
        WHERE sku=?
        """,
        (row["sku"],),
    )
    conn.commit()
    product = dict(
        conn.execute("SELECT * FROM products WHERE sku=?", (row["sku"],)).fetchone()
    )
    signals = [
        DemandSignal(
            query=str(product.get("upc") or product.get("mpn") or product["sku"]),
            query_type="upc" if product.get("upc") else "mpn",
            upc=product.get("upc"),
            mpn=product.get("mpn"),
            manufacturer=product.get("manufacturer"),
            sold_count=5,
            active_count=2,
            repeated_demand=True,
            lowest_price=float(product.get("map") or 100),
            median_price=float(product.get("map") or 100),
            provisional_public_ebay=True,
            needs_official_ebay_validation=True,
        )
    ]
    out = discover_ebay_demand_first(
        settings=settings,
        snapshot_id="20260903_1744",
        demand_provider=ProvisionalPublicDemandProvider(signals),
    )
    assert out["summary"]["pipeline_source"] == PIPELINE_EBAY_DEMAND_FIRST
    assert out["summary"]["signals_seen"] == 1
    assert out["summary"]["matched_catalog"] >= 1
    if out["survivors"]:
        s0 = out["survivors"][0]
        assert s0["pipeline_source"] == PIPELINE_EBAY_DEMAND_FIRST
        assert s0["cohort"] in {
            COHORT_SAFE_NATIONWIDE,
            COHORT_DESTINATION_SENSITIVE,
            COHORT_QUARANTINE_UNRESOLVED,
        }
        assert "comparison_cohort_id" in s0
        assert s0.get("sell_through") is None


def test_ebay_demand_first_scaffolded_empty(settings: Settings):
    ingest_stub(settings)
    out = discover_ebay_demand_first(
        settings=settings,
        snapshot_id="20260903_1744",
        demand_provider=ProvisionalPublicDemandProvider([]),
    )
    assert out["summary"]["status"] == "scaffolded_no_live_matches"
    assert out["summary"]["sellable_survivors"] == 0

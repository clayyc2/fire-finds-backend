"""Unit tests for deterministic Ops exception rules."""

from __future__ import annotations

import json

from firefinds.action_log.logger import ActionLogger
from firefinds.config import Settings
from firefinds.db.schema import init_db
from firefinds.ops.exceptions import (
    GLOBAL_ACCOUNT_SKU,
    GLOBAL_INGEST_SKU,
    RULE_ACCOUNT_HEALTH_RISK,
    RULE_API_INGEST_FAILURE_STREAK,
    RULE_CANCELLATION_RATE_HIGH,
    RULE_CHANNEL_AUTH_FAIL,
    RULE_COST_SPIKE,
    RULE_CS_EXCEPTION_OPEN,
    RULE_DUPLICATE_LISTING,
    RULE_FULFILLMENT_LATE,
    RULE_INVALID_LISTING,
    RULE_MAP_BREACH,
    RULE_MARGIN_BELOW_MIN,
    RULE_PROFIT_BELOW_MIN,
    RULE_RETURNS_RATE_HIGH,
    RULE_SHIPPING_UNRESOLVED,
    RULE_STOCK_LEQ_BUFFER,
    RULE_TRACKING_MISSING,
    evaluate_candidate,
    ingest_failure_streak,
    list_exceptions,
    rule_catalog,
    scan_exceptions,
)
from firefinds.cli.main import main


def _base_ok(**overrides):
    row = {
        "sku": "SKU-OK",
        "stock": 10,
        "shipping_status": "RESOLVED",
        "listable_profit": 20.0,
        "listable_margin": 0.20,
        "contribution_profit": 20.0,
        "contribution_margin": 0.20,
        "map": 50.0,
        "sell_comp": 55.0,
        "map_ok": 1,
        "channel_ok": 1,
        "opportunity_only": 0,
    }
    row.update(overrides)
    return row


def test_rule_stock_leq_buffer(settings: Settings):
    hits = evaluate_candidate(_base_ok(stock=2), settings)
    codes = {h.rule_code for h in hits}
    assert RULE_STOCK_LEQ_BUFFER in codes
    hits_ok = evaluate_candidate(_base_ok(stock=3), settings)
    assert RULE_STOCK_LEQ_BUFFER not in {h.rule_code for h in hits_ok}


def test_rule_shipping_unresolved(settings: Settings):
    hits = evaluate_candidate(_base_ok(shipping_status="UNRESOLVED"), settings)
    assert RULE_SHIPPING_UNRESOLVED in {h.rule_code for h in hits}
    hits_ok = evaluate_candidate(_base_ok(shipping_status="RESOLVED"), settings)
    assert RULE_SHIPPING_UNRESOLVED not in {h.rule_code for h in hits_ok}


def test_rule_profit_below_min(settings: Settings):
    hits = evaluate_candidate(_base_ok(listable_profit=7.99), settings)
    assert RULE_PROFIT_BELOW_MIN in {h.rule_code for h in hits}
    hits_ok = evaluate_candidate(_base_ok(listable_profit=8.0), settings)
    assert RULE_PROFIT_BELOW_MIN not in {h.rule_code for h in hits_ok}


def test_rule_margin_below_min(settings: Settings):
    hits = evaluate_candidate(_base_ok(listable_margin=0.119), settings)
    assert RULE_MARGIN_BELOW_MIN in {h.rule_code for h in hits}
    hits_ok = evaluate_candidate(_base_ok(listable_margin=0.12), settings)
    assert RULE_MARGIN_BELOW_MIN not in {h.rule_code for h in hits_ok}


def test_rule_map_breach(settings: Settings):
    hits = evaluate_candidate(_base_ok(map=100.0, sell_comp=99.99), settings)
    assert RULE_MAP_BREACH in {h.rule_code for h in hits}
    hits_flag = evaluate_candidate(
        _base_ok(map=100.0, sell_comp=None, map_ok=0), settings
    )
    assert RULE_MAP_BREACH in {h.rule_code for h in hits_flag}
    hits_ok = evaluate_candidate(_base_ok(map=100.0, sell_comp=100.0), settings)
    assert RULE_MAP_BREACH not in {h.rule_code for h in hits_ok}


def test_rule_channel_auth_fail(settings: Settings):
    hits = evaluate_candidate(_base_ok(channel_ok=0), settings)
    assert RULE_CHANNEL_AUTH_FAIL in {h.rule_code for h in hits}
    hits_oo = evaluate_candidate(
        _base_ok(opportunity_only=1, channel_ok=None), settings
    )
    assert RULE_CHANNEL_AUTH_FAIL in {h.rule_code for h in hits_oo}
    hits_ok = evaluate_candidate(_base_ok(channel_ok=1, opportunity_only=0), settings)
    assert RULE_CHANNEL_AUTH_FAIL not in {h.rule_code for h in hits_ok}


def test_rule_api_ingest_failure_streak(settings: Settings):
    conn = init_db(settings.db_path)
    logger = ActionLogger(settings.actions_jsonl, conn=conn)
    for _ in range(3):
        logger.log("ingest-live", decision="failed", detail={"err": "timeout"})
    hit = ingest_failure_streak(conn, threshold=3)
    assert hit is not None
    assert hit.rule_code == RULE_API_INGEST_FAILURE_STREAK
    logger.log("ingest-live", decision="ok", detail={"n": 1})
    assert ingest_failure_streak(conn, threshold=3) is None
    conn.close()


def test_scan_persists_exceptions_and_pauses(settings: Settings):
    conn = init_db(settings.db_path)
    conn.execute(
        """
        INSERT INTO products (
            sku, stock, shipping_status, listable_profit, listable_margin,
            contribution_profit, contribution_margin, map, sell_comp,
            map_ok, channel_ok, opportunity_only, paused
        ) VALUES (
            'BAD-1', 1, 'UNRESOLVED', 5.0, 0.05,
            5.0, 0.05, 80.0, 70.0,
            0, 0, 0, 0
        )
        """
    )
    conn.execute(
        """
        INSERT INTO candidate_cohorts (
            sku, pipeline_source, cohort, comparison_cohort_id, snapshot_id,
            rank, listable_profit, listable_margin, sell_comp, map,
            shipping_status
        ) VALUES (
            'BAD-1', 'RANDMAR_FIRST', 'SAFE_NATIONWIDE', 'cmp', 'snap1',
            1, 5.0, 0.05, 70.0, 80.0,
            'UNRESOLVED'
        )
        """
    )
    conn.commit()
    summary = scan_exceptions(
        settings=settings, snapshot_id="snap1", conn=conn, apply_pause=True
    )
    assert summary["scanned"] == 1
    assert summary["created"] >= 1
    assert "BAD-1" in summary["paused_skus"]
    assert summary["hits_by_rule"][RULE_STOCK_LEQ_BUFFER] >= 1
    assert summary["hits_by_rule"][RULE_SHIPPING_UNRESOLVED] >= 1
    assert summary["hits_by_rule"][RULE_PROFIT_BELOW_MIN] >= 1
    assert summary["hits_by_rule"][RULE_MARGIN_BELOW_MIN] >= 1
    assert summary["hits_by_rule"][RULE_MAP_BREACH] >= 1
    assert summary["hits_by_rule"][RULE_CHANNEL_AUTH_FAIL] >= 1

    paused = conn.execute(
        "SELECT paused, pause_reason FROM products WHERE sku='BAD-1'"
    ).fetchone()
    assert paused["paused"] == 1
    assert "STOCK_LEQ_BUFFER" in (paused["pause_reason"] or "")

    rows = list_exceptions(settings=settings, conn=conn, status="open,paused")
    codes = {r["rule_code"] for r in rows}
    assert RULE_STOCK_LEQ_BUFFER in codes
    assert RULE_MAP_BREACH in codes

    actions = conn.execute(
        "SELECT action, decision FROM actions WHERE sku='BAD-1' AND action='ops_exception'"
    ).fetchall()
    assert len(actions) >= 1
    conn.close()


def test_scan_ingest_streak_global(settings: Settings):
    conn = init_db(settings.db_path)
    logger = ActionLogger(settings.actions_jsonl, conn=conn)
    for _ in range(3):
        logger.log("api_ingest", decision="error", detail={"x": 1})
    summary = scan_exceptions(settings=settings, conn=conn, apply_pause=True)
    assert summary["hits_by_rule"][RULE_API_INGEST_FAILURE_STREAK] == 1
    rows = list_exceptions(
        settings=settings,
        conn=conn,
        rule_code=RULE_API_INGEST_FAILURE_STREAK,
        status="open,paused",
    )
    assert len(rows) == 1
    assert rows[0]["sku"] == GLOBAL_INGEST_SKU
    conn.close()


def test_rule_catalog_lists_all_sixteen():
    codes = {r["code"] for r in rule_catalog()}
    assert codes == {
        RULE_STOCK_LEQ_BUFFER,
        RULE_SHIPPING_UNRESOLVED,
        RULE_PROFIT_BELOW_MIN,
        RULE_MARGIN_BELOW_MIN,
        RULE_MAP_BREACH,
        RULE_CHANNEL_AUTH_FAIL,
        RULE_API_INGEST_FAILURE_STREAK,
        RULE_COST_SPIKE,
        RULE_RETURNS_RATE_HIGH,
        RULE_CANCELLATION_RATE_HIGH,
        RULE_CS_EXCEPTION_OPEN,
        RULE_ACCOUNT_HEALTH_RISK,
        RULE_TRACKING_MISSING,
        RULE_FULFILLMENT_LATE,
        RULE_DUPLICATE_LISTING,
        RULE_INVALID_LISTING,
    }


def test_cli_ops_exceptions_scan_list(monkeypatch, tmp_path, capsys):
    db = tmp_path / "cli.db"
    jsonl = tmp_path / "a.jsonl"
    monkeypatch.setenv("FIREFINDS_DB_PATH", str(db))
    monkeypatch.setenv("FIREFINDS_ACTIONS_JSONL", str(jsonl))
    monkeypatch.setenv("LIVE_LISTINGS_ENABLED", "false")
    monkeypatch.setenv("SUPPLIER_ORDERS_ENABLED", "false")
    conn = init_db(db)
    conn.execute(
        """
        INSERT INTO products (sku, stock, shipping_status, listable_profit,
            listable_margin, map, sell_comp, map_ok, channel_ok)
        VALUES ('CLI-1', 0, 'RESOLVED', 20, 0.2, 10, 12, 1, 1)
        """
    )
    conn.execute(
        """
        INSERT INTO candidate_cohorts (
            sku, pipeline_source, cohort, comparison_cohort_id, snapshot_id
        ) VALUES ('CLI-1', 'RANDMAR_FIRST', 'SAFE_NATIONWIDE', 'c', 's')
        """
    )
    conn.commit()
    conn.close()

    rc = main(["ops-exceptions", "scan", "--snapshot-id", "s"])
    assert rc == 0
    out = capsys.readouterr().out
    summary = json.loads(out)
    assert summary["paused_count"] >= 1

    rc = main(["ops-exceptions", "list", "--sku", "CLI-1"])
    assert rc == 0
    listed = json.loads(capsys.readouterr().out)
    assert any(r["rule_code"] == RULE_STOCK_LEQ_BUFFER for r in listed)

    rc = main(["ops-exceptions", "rules"])
    assert rc == 0
    catalog = json.loads(capsys.readouterr().out)
    assert len(catalog) == 16


def test_connect_sets_busy_timeout(tmp_path):
    from firefinds.db.schema import connect

    conn = connect(tmp_path / "busy.db")
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 30000
    conn.close()


def test_scan_retries_on_database_locked(settings: Settings, monkeypatch):
    """Lock during init_db should retry rather than surface a zero/empty summary."""
    import sqlite3

    from firefinds.ops import exceptions as ex

    calls = {"n": 0}
    real_init = ex.init_db

    def flaky_init(path):
        calls["n"] += 1
        if calls["n"] < 3:
            raise sqlite3.OperationalError("database is locked")
        return real_init(path)

    monkeypatch.setattr(ex, "init_db", flaky_init)
    monkeypatch.setattr(ex.time, "sleep", lambda _s: None)

    conn = real_init(settings.db_path)
    conn.execute(
        """
        INSERT INTO products (sku, stock, shipping_status, listable_profit,
            listable_margin, map, sell_comp, map_ok, channel_ok)
        VALUES ('LOCK-1', 0, 'RESOLVED', 20, 0.2, 10, 12, 1, 1)
        """
    )
    conn.execute(
        """
        INSERT INTO candidate_cohorts (
            sku, pipeline_source, cohort, comparison_cohort_id, snapshot_id
        ) VALUES ('LOCK-1', 'RANDMAR_FIRST', 'SAFE_NATIONWIDE', 'c', 'snap-lock')
        """
    )
    conn.commit()
    conn.close()

    summary = scan_exceptions(
        settings=settings, snapshot_id="snap-lock", apply_pause=True
    )
    assert calls["n"] == 3
    assert summary["scanned"] == 1
    assert summary["paused_count"] == 1
    assert summary["hits_by_rule"][RULE_STOCK_LEQ_BUFFER] == 1


def test_rule_cost_spike(settings: Settings):
    hits = evaluate_candidate(
        _base_ok(dealer_cost=125.7, last_known_cost=100.0), settings
    )
    assert RULE_COST_SPIKE in {h.rule_code for h in hits}
    msg = next(h.message for h in hits if h.rule_code == RULE_COST_SPIKE)
    assert "25.7%" in msg
    hits_ok = evaluate_candidate(
        _base_ok(dealer_cost=109.0, last_known_cost=100.0), settings
    )
    assert RULE_COST_SPIKE not in {h.rule_code for h in hits_ok}
    # Exactly 10% still trips (>= threshold)
    hits_eq = evaluate_candidate(
        _base_ok(dealer_cost=110.0, last_known_cost=100.0), settings
    )
    assert RULE_COST_SPIKE in {h.rule_code for h in hits_eq}


def test_rule_returns_rate_high(settings: Settings):
    hits = evaluate_candidate(
        _base_ok(returns=2, sales_units=10), settings
    )
    assert RULE_RETURNS_RATE_HIGH in {h.rule_code for h in hits}
    hits_low_n = evaluate_candidate(
        _base_ok(returns=1, sales_units=4), settings
    )
    assert RULE_RETURNS_RATE_HIGH not in {h.rule_code for h in hits_low_n}
    hits_ok = evaluate_candidate(
        _base_ok(returns=0, sales_units=10), settings
    )
    assert RULE_RETURNS_RATE_HIGH not in {h.rule_code for h in hits_ok}


def test_rule_cancellation_rate_high(settings: Settings):
    # 3 / (10+3) ≈ 23.1%
    hits = evaluate_candidate(
        _base_ok(cancellations=3, sales_units=10), settings
    )
    hit = next(h for h in hits if h.rule_code == RULE_CANCELLATION_RATE_HIGH)
    assert hit.severity == "pause"
    assert "23.1%" in hit.message
    hits_buyer = evaluate_candidate(
        _base_ok(cancellations=3, sales_units=10, cancel_fault="buyer"),
        settings,
    )
    hit_b = next(
        h for h in hits_buyer if h.rule_code == RULE_CANCELLATION_RATE_HIGH
    )
    assert hit_b.severity == "flag"
    hits_ok = evaluate_candidate(
        _base_ok(cancellations=0, sales_units=10), settings
    )
    assert RULE_CANCELLATION_RATE_HIGH not in {h.rule_code for h in hits_ok}


def test_rule_cs_exception_open(settings: Settings):
    hits = evaluate_candidate(
        _base_ok(cs_open=1, cs_open_hours=24), settings
    )
    assert RULE_CS_EXCEPTION_OPEN in {h.rule_code for h in hits}
    hits_short = evaluate_candidate(
        _base_ok(cs_open=1, cs_open_hours=23.9), settings
    )
    assert RULE_CS_EXCEPTION_OPEN not in {h.rule_code for h in hits_short}
    hits_detail = evaluate_candidate(
        _base_ok(detail_json={"cs_open": 1, "cs_open_hours": 30}), settings
    )
    assert RULE_CS_EXCEPTION_OPEN in {h.rule_code for h in hits_detail}


def test_rule_account_health_risk(settings: Settings):
    hits = evaluate_candidate(
        _base_ok(sku=GLOBAL_ACCOUNT_SKU, account_defect_rate=0.03), settings
    )
    assert RULE_ACCOUNT_HEALTH_RISK in {h.rule_code for h in hits}
    hits_strike = evaluate_candidate(_base_ok(policy_strike=1), settings)
    assert RULE_ACCOUNT_HEALTH_RISK in {h.rule_code for h in hits_strike}
    hits_limit = evaluate_candidate(_base_ok(selling_limit_hit=1), settings)
    assert RULE_ACCOUNT_HEALTH_RISK in {h.rule_code for h in hits_limit}
    hits_ok = evaluate_candidate(
        _base_ok(account_defect_rate=0.02, policy_strike=0, selling_limit_hit=0),
        settings,
    )
    assert RULE_ACCOUNT_HEALTH_RISK not in {h.rule_code for h in hits_ok}


def test_rule_tracking_missing(settings: Settings):
    hits = evaluate_candidate(
        _base_ok(
            order_status="SIMULATED_ORDER",
            hours_since_order=60.0,
            tracking_number=None,
        ),
        settings,
    )
    assert RULE_TRACKING_MISSING in {h.rule_code for h in hits}
    hits_tracked = evaluate_candidate(
        _base_ok(
            order_status="AWAITING_SHIP",
            hours_since_order=60.0,
            tracking_number="1Z999",
        ),
        settings,
    )
    assert RULE_TRACKING_MISSING not in {h.rule_code for h in hits_tracked}
    hits_early = evaluate_candidate(
        _base_ok(
            order_status="SIMULATED_ORDER",
            hours_since_order=48.0,
            tracking_number="",
        ),
        settings,
    )
    assert RULE_TRACKING_MISSING not in {h.rule_code for h in hits_early}


def test_rule_fulfillment_late(settings: Settings):
    hits = evaluate_candidate(
        _base_ok(
            order_status="SIMULATED_ORDER",
            hours_since_order=96.0,
            ship_status="AWAITING_SHIP",
            tracking_number=None,
        ),
        settings,
    )
    codes = {h.rule_code for h in hits}
    assert RULE_FULFILLMENT_LATE in codes
    assert RULE_TRACKING_MISSING in codes
    hits_shipped = evaluate_candidate(
        _base_ok(
            order_status="SIMULATED_ORDER",
            hours_since_order=96.0,
            ship_status="SHIPPED",
            tracking_number="1Z",
        ),
        settings,
    )
    assert RULE_FULFILLMENT_LATE not in {h.rule_code for h in hits_shipped}


def test_rule_duplicate_listing(settings: Settings):
    hits = evaluate_candidate(_base_ok(active_offer_count=2), settings)
    assert RULE_DUPLICATE_LISTING in {h.rule_code for h in hits}
    hits_ok = evaluate_candidate(_base_ok(active_offer_count=1), settings)
    assert RULE_DUPLICATE_LISTING not in {h.rule_code for h in hits_ok}


def test_rule_invalid_listing(settings: Settings):
    hits = evaluate_candidate(_base_ok(listing_validation_ok=0), settings)
    assert RULE_INVALID_LISTING in {h.rule_code for h in hits}
    hits_id = evaluate_candidate(_base_ok(identity_mismatch=1), settings)
    assert RULE_INVALID_LISTING in {h.rule_code for h in hits_id}
    hits_miss = evaluate_candidate(
        _base_ok(missing_specifics=["Brand"]), settings
    )
    assert RULE_INVALID_LISTING in {h.rule_code for h in hits_miss}
    hits_ok = evaluate_candidate(
        _base_ok(
            listing_validation_ok=1,
            identity_mismatch=0,
            missing_specifics=0,
        ),
        settings,
    )
    assert RULE_INVALID_LISTING not in {h.rule_code for h in hits_ok}


def test_scan_account_health_sentinel(settings: Settings):
    conn = init_db(settings.db_path)
    conn.execute(
        """
        INSERT INTO products (sku, stock, shipping_status, listable_profit,
            listable_margin, map, sell_comp, map_ok, channel_ok,
            account_defect_rate, policy_strike)
        VALUES (?, 10, 'RESOLVED', 20, 0.2, 10, 12, 1, 1, 0.05, 0)
        """,
        (GLOBAL_ACCOUNT_SKU,),
    )
    conn.commit()
    summary = scan_exceptions(settings=settings, conn=conn, apply_pause=True)
    assert summary["hits_by_rule"].get(RULE_ACCOUNT_HEALTH_RISK, 0) == 1
    assert GLOBAL_ACCOUNT_SKU not in summary["paused_skus"]
    rows = list_exceptions(
        settings=settings,
        conn=conn,
        rule_code=RULE_ACCOUNT_HEALTH_RISK,
        status="open,paused",
    )
    assert len(rows) == 1
    assert rows[0]["sku"] == GLOBAL_ACCOUNT_SKU
    conn.close()


def test_scan_new_unlock_rules_persist(settings: Settings):
    conn = init_db(settings.db_path)
    conn.execute(
        """
        INSERT INTO products (
            sku, stock, shipping_status, listable_profit, listable_margin,
            contribution_profit, contribution_margin, map, sell_comp,
            map_ok, channel_ok, opportunity_only, paused,
            dealer_cost, last_known_cost, returns, sales_units,
            cancellations, active_offer_count, listing_validation_ok,
            order_status, hours_since_order, tracking_number, ship_status,
            cs_open, cs_open_hours, listing_status
        ) VALUES (
            'UNLOCK-1', 10, 'RESOLVED', 20.0, 0.20,
            20.0, 0.20, 50.0, 55.0,
            1, 1, 0, 0,
            125.7, 100.0, 2, 10,
            3, 2, 0,
            'SIMULATED_ORDER', 96.0, NULL, 'AWAITING_SHIP',
            1, 30.0, 'SIMULATED_LISTED'
        )
        """
    )
    conn.execute(
        """
        INSERT INTO candidate_cohorts (
            sku, pipeline_source, cohort, comparison_cohort_id, snapshot_id,
            rank, listable_profit, listable_margin, sell_comp, map,
            shipping_status, returns, cancellations, sales_units
        ) VALUES (
            'UNLOCK-1', 'RANDMAR_FIRST', 'SAFE_NATIONWIDE', 'cmp', 'snap-u',
            1, 20.0, 0.20, 55.0, 50.0,
            'RESOLVED', 2, 3, 10
        )
        """
    )
    conn.commit()
    summary = scan_exceptions(
        settings=settings, snapshot_id="snap-u", conn=conn, apply_pause=True
    )
    assert summary["scanned"] >= 1
    h = summary["hits_by_rule"]
    assert h.get(RULE_COST_SPIKE, 0) >= 1
    assert h.get(RULE_RETURNS_RATE_HIGH, 0) >= 1
    assert h.get(RULE_CANCELLATION_RATE_HIGH, 0) >= 1
    assert h.get(RULE_DUPLICATE_LISTING, 0) >= 1
    assert h.get(RULE_INVALID_LISTING, 0) >= 1
    assert h.get(RULE_TRACKING_MISSING, 0) >= 1
    assert h.get(RULE_FULFILLMENT_LATE, 0) >= 1
    assert h.get(RULE_CS_EXCEPTION_OPEN, 0) >= 1
    assert "UNLOCK-1" in summary["paused_skus"]
    conn.close()

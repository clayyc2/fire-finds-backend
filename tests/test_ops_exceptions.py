"""Unit tests for deterministic Ops exception rules."""

from __future__ import annotations

import json

from firefinds.action_log.logger import ActionLogger
from firefinds.config import Settings
from firefinds.db.schema import init_db
from firefinds.ops.exceptions import (
    GLOBAL_INGEST_SKU,
    RULE_API_INGEST_FAILURE_STREAK,
    RULE_CHANNEL_AUTH_FAIL,
    RULE_MAP_BREACH,
    RULE_MARGIN_BELOW_MIN,
    RULE_PROFIT_BELOW_MIN,
    RULE_SHIPPING_UNRESOLVED,
    RULE_STOCK_LEQ_BUFFER,
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


def test_rule_catalog_lists_all_seven():
    codes = {r["code"] for r in rule_catalog()}
    assert codes == {
        RULE_STOCK_LEQ_BUFFER,
        RULE_SHIPPING_UNRESOLVED,
        RULE_PROFIT_BELOW_MIN,
        RULE_MARGIN_BELOW_MIN,
        RULE_MAP_BREACH,
        RULE_CHANNEL_AUTH_FAIL,
        RULE_API_INGEST_FAILURE_STREAK,
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
    assert len(catalog) == 7


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

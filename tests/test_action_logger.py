"""Action logger writes JSONL + SQLite."""

from __future__ import annotations

import json
from pathlib import Path

from firefinds.action_log.logger import ActionLogger
from firefinds.config import Settings
from firefinds.db.schema import init_db


def test_logger_jsonl_and_sqlite(settings: Settings):
    conn = init_db(settings.db_path)
    logger = ActionLogger(settings.actions_jsonl, conn=conn)
    rec = logger.log(
        "score",
        sku="ABC",
        decision="pass",
        detail={"profit": 12.5},
        source="test",
    )
    assert rec["action"] == "score"
    assert settings.actions_jsonl.is_file()
    lines = settings.actions_jsonl.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["sku"] == "ABC"
    assert parsed["decision"] == "pass"

    row = conn.execute(
        "SELECT action, sku, decision FROM actions WHERE sku=?", ("ABC",)
    ).fetchone()
    assert row["action"] == "score"
    assert row["decision"] == "pass"
    logger.close()


def test_logger_redacts_secret_keys(settings: Settings, tmp_path: Path):
    path = tmp_path / "a.jsonl"
    logger = ActionLogger(path)
    logger.log("auth", detail={"client_secret": "SHOULD_NOT_APPEAR", "ok": 1})
    text = path.read_text(encoding="utf-8")
    assert "SHOULD_NOT_APPEAR" not in text
    assert "[redacted]" in text


def test_init_db_migrates_legacy_products_before_indexes(tmp_path: Path):
    import sqlite3

    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        """
        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            sku TEXT NOT NULL UNIQUE,
            score REAL,
            score_pass INTEGER DEFAULT 0,
            paused INTEGER DEFAULT 0
        )
        """
    )
    conn.execute(
        "INSERT INTO products (sku, score, score_pass) VALUES ('LEGACY-1', 10, 1)"
    )
    conn.commit()
    conn.close()
    migrated = init_db(db)
    cols = {r[1] for r in migrated.execute("PRAGMA table_info(products)")}
    assert "eligible" in cols
    assert "ship_p75" in cols
    assert "fails_expensive_destinations" in cols
    tables = {
        r[0]
        for r in migrated.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "shipping_quotes" in tables
    eligible = migrated.execute(
        "SELECT eligible FROM products WHERE sku='LEGACY-1'"
    ).fetchone()[0]
    assert eligible == 1

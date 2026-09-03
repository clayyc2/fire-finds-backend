"""SQLite schema for products and action log."""

from __future__ import annotations

import sqlite3
from pathlib import Path

PRODUCTS_DDL = """
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL UNIQUE,
    upc TEXT,
    mpn TEXT,
    manufacturer TEXT,
    map REAL,
    msrp REAL,
    dealer_cost REAL,
    rebate REAL DEFAULT 0,
    stock INTEGER DEFAULT 0,
    landed_cost REAL,
    -- scored fields
    contribution_profit REAL,
    contribution_margin REAL,
    score REAL,
    score_pass INTEGER DEFAULT 0,
    score_reason TEXT,
    -- pause flags
    paused INTEGER DEFAULT 0,
    pause_reason TEXT,
    -- timestamps
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    scored_at TEXT
);
"""

ACTIONS_DDL = """
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL DEFAULT (datetime('now')),
    action TEXT NOT NULL,
    sku TEXT,
    decision TEXT,
    detail_json TEXT,
    source TEXT
);
"""

INDEXES_DDL = [
    "CREATE INDEX IF NOT EXISTS idx_products_score ON products(score DESC);",
    "CREATE INDEX IF NOT EXISTS idx_products_score_pass ON products(score_pass);",
    "CREATE INDEX IF NOT EXISTS idx_actions_ts ON actions(ts);",
    "CREATE INDEX IF NOT EXISTS idx_actions_sku ON actions(sku);",
]


def connect(db_path: Path | str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: Path | str) -> sqlite3.Connection:
    conn = connect(db_path)
    conn.executescript(PRODUCTS_DDL)
    conn.executescript(ACTIONS_DDL)
    for ddl in INDEXES_DDL:
        conn.execute(ddl)
    conn.commit()
    return conn

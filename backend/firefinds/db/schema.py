"""SQLite schema for products (incl. measurable outcomes), competition, ranked queue, and action log."""

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
    contribution_profit REAL,
    contribution_margin REAL,
    score REAL,
    score_pass INTEGER DEFAULT 0,
    score_reason TEXT,
    paused INTEGER DEFAULT 0,
    pause_reason TEXT,
    eligible INTEGER DEFAULT 0,
    title TEXT,
    category TEXT,
    product_type TEXT,
    opportunity_only INTEGER DEFAULT 0,
    unit_weight REAL,
    qty_montreal INTEGER DEFAULT 0,
    qty_toronto INTEGER DEFAULT 0,
    qty_vancouver INTEGER DEFAULT 0,
    qty_laval INTEGER DEFAULT 0,
    qty_edmonton INTEGER DEFAULT 0,
    net_cost REAL,
    ship_est REAL,
    ship_warehouse TEXT,
    ship_model TEXT,
    upc_norm TEXT,
    upc_valid INTEGER DEFAULT 0,
    mpn_norm TEXT,
    ebay_comp_lowest REAL,
    ebay_comp_median REAL,
    ebay_comp_count INTEGER DEFAULT 0,
    ebay_comp_url TEXT,
    ebay_comp_query TEXT,
    ebay_comp_query_type TEXT,
    ebay_comp_at TEXT,
    sell_comp REAL,
    listable INTEGER DEFAULT 0,
    listable_pass INTEGER DEFAULT 0,
    listable_rank INTEGER,
    listable_reason TEXT,
    listable_profit REAL,
    listable_margin REAL,
    sales_probability REAL,
    expected_monthly_units REAL,
    expected_monthly_contribution_profit REAL,
    rank_score REAL,
    provisional_public_ebay INTEGER DEFAULT 0,
    needs_official_ebay_validation INTEGER DEFAULT 1,
    return_risk_score REAL,
    dedupe_kept INTEGER DEFAULT 1,
    shipping_status TEXT,
    final_profitability INTEGER DEFAULT 0,
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

EBAY_COMPETITION_DDL = """
CREATE TABLE IF NOT EXISTS ebay_competition (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL,
    queried_at TEXT NOT NULL DEFAULT (datetime('now')),
    query TEXT,
    query_type TEXT,
    item_count INTEGER DEFAULT 0,
    lowest_price REAL,
    median_price REAL,
    sample_url TEXT,
    sell_comp REAL,
    contribution_profit REAL,
    contribution_margin REAL,
    listable_pass INTEGER DEFAULT 0,
    reason TEXT,
    provisional_public_ebay INTEGER DEFAULT 0,
    needs_official_ebay_validation INTEGER DEFAULT 1,
    UNIQUE(sku, queried_at)
);
"""

RANKED_QUEUE_DDL = """
CREATE TABLE IF NOT EXISTS ranked_queue (
    rank INTEGER NOT NULL,
    sku TEXT NOT NULL UNIQUE,
    rank_score REAL,
    expected_monthly_contribution_profit REAL,
    sales_probability REAL,
    sell_comp REAL,
    listable_profit REAL,
    listable_margin REAL,
    map REAL,
    stock INTEGER,
    provisional_public_ebay INTEGER DEFAULT 0,
    needs_official_ebay_validation INTEGER DEFAULT 1,
    reason TEXT,
    ship_p75 REAL,
    shipping_status TEXT,
    fails_expensive_destinations INTEGER DEFAULT 0,
    failed_expensive_destinations TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

SHIPPING_QUOTES_DDL = """
CREATE TABLE IF NOT EXISTS shipping_quotes (
    sku TEXT NOT NULL,
    dest_id TEXT NOT NULL,
    city TEXT,
    province TEXT,
    postal_code TEXT,
    cost_cad REAL,
    status TEXT,
    warehouse TEXT,
    carrier TEXT,
    method_id TEXT,
    source TEXT,
    quoted_at TEXT NOT NULL DEFAULT (datetime('now')),
    detail_json TEXT,
    PRIMARY KEY (sku, dest_id)
);
"""


CANDIDATE_COHORTS_DDL = """
CREATE TABLE IF NOT EXISTS candidate_cohorts (
    sku TEXT NOT NULL,
    pipeline_source TEXT NOT NULL,
    cohort TEXT NOT NULL,
    comparison_cohort_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    rank INTEGER,
    fails_expensive_destinations INTEGER DEFAULT 0,
    listable_profit REAL,
    listable_margin REAL,
    sell_comp REAL,
    map REAL,
    ship_p75 REAL,
    shipping_status TEXT,
    sell_through REAL,
    time_to_first_sale REAL,
    contribution_profit_realized REAL,
    cancellations INTEGER,
    returns INTEGER,
    impressions REAL,
    ctr REAL,
    conversion_rate REAL,
    sales_units REAL,
    match_confidence TEXT,
    creative_version_id TEXT,
    creative_variant TEXT,
    ab_assignment TEXT,
    detail_json TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (sku, pipeline_source, snapshot_id)
);
"""

QUARANTINE_UNRESOLVED_DDL = """
CREATE TABLE IF NOT EXISTS quarantine_unresolved_shipping (
    sku TEXT NOT NULL,
    pipeline_source TEXT NOT NULL DEFAULT 'RANDMAR_FIRST',
    snapshot_id TEXT NOT NULL,
    shipping_status TEXT,
    listable_pass INTEGER DEFAULT 0,
    score REAL,
    map REAL,
    stock INTEGER,
    reason TEXT,
    comparison_cohort_id TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (sku, pipeline_source, snapshot_id)
);
"""


OPS_EXCEPTIONS_DDL = """
CREATE TABLE IF NOT EXISTS ops_exceptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL,
    rule_code TEXT NOT NULL,
    severity TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    message TEXT,
    detail_json TEXT,
    snapshot_id TEXT,
    pipeline_source TEXT,
    cohort TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at TEXT
);
"""

INDEXES_DDL = [
    "CREATE INDEX IF NOT EXISTS idx_products_score ON products(score DESC);",
    "CREATE INDEX IF NOT EXISTS idx_products_score_pass ON products(score_pass);",
    "CREATE INDEX IF NOT EXISTS idx_products_eligible ON products(eligible);",
    "CREATE INDEX IF NOT EXISTS idx_products_listable_pass ON products(listable_pass);",
    "CREATE INDEX IF NOT EXISTS idx_products_rank_score ON products(rank_score DESC);",
    "CREATE INDEX IF NOT EXISTS idx_products_upc_norm ON products(upc_norm);",
    "CREATE INDEX IF NOT EXISTS idx_products_mpn_norm ON products(mpn_norm);",
    "CREATE INDEX IF NOT EXISTS idx_actions_ts ON actions(ts);",
    "CREATE INDEX IF NOT EXISTS idx_actions_sku ON actions(sku);",
    "CREATE INDEX IF NOT EXISTS idx_ebay_comp_sku ON ebay_competition(sku);",
    "CREATE INDEX IF NOT EXISTS idx_ranked_queue_rank ON ranked_queue(rank);",
    "CREATE INDEX IF NOT EXISTS idx_shipping_quotes_sku ON shipping_quotes(sku);",
    "CREATE INDEX IF NOT EXISTS idx_candidate_cohorts_cohort ON candidate_cohorts(cohort);",
    "CREATE INDEX IF NOT EXISTS idx_candidate_cohorts_pipeline ON candidate_cohorts(pipeline_source);",
    "CREATE INDEX IF NOT EXISTS idx_quarantine_unresolved_sku ON quarantine_unresolved_shipping(sku);",
    "CREATE INDEX IF NOT EXISTS idx_ops_exceptions_sku ON ops_exceptions(sku);",
    "CREATE INDEX IF NOT EXISTS idx_ops_exceptions_rule ON ops_exceptions(rule_code);",
    "CREATE INDEX IF NOT EXISTS idx_ops_exceptions_status ON ops_exceptions(status);",
]

PRODUCT_COLUMN_MIGRATIONS: list[tuple[str, str]] = [
    ("eligible", "INTEGER DEFAULT 0"),
    ("title", "TEXT"),
    ("category", "TEXT"),
    ("product_type", "TEXT"),
    ("opportunity_only", "INTEGER DEFAULT 0"),
    ("unit_weight", "REAL"),
    ("qty_montreal", "INTEGER DEFAULT 0"),
    ("qty_toronto", "INTEGER DEFAULT 0"),
    ("qty_vancouver", "INTEGER DEFAULT 0"),
    ("qty_laval", "INTEGER DEFAULT 0"),
    ("qty_edmonton", "INTEGER DEFAULT 0"),
    ("net_cost", "REAL"),
    ("ship_est", "REAL"),
    ("ship_warehouse", "TEXT"),
    ("ship_model", "TEXT"),
    ("upc_norm", "TEXT"),
    ("upc_valid", "INTEGER DEFAULT 0"),
    ("mpn_norm", "TEXT"),
    ("ebay_comp_lowest", "REAL"),
    ("ebay_comp_median", "REAL"),
    ("ebay_comp_count", "INTEGER DEFAULT 0"),
    ("ebay_comp_url", "TEXT"),
    ("ebay_comp_query", "TEXT"),
    ("ebay_comp_query_type", "TEXT"),
    ("ebay_comp_at", "TEXT"),
    ("sell_comp", "REAL"),
    ("listable", "INTEGER DEFAULT 0"),
    ("listable_pass", "INTEGER DEFAULT 0"),
    ("listable_rank", "INTEGER"),
    ("listable_reason", "TEXT"),
    ("listable_profit", "REAL"),
    ("listable_margin", "REAL"),
    ("sales_probability", "REAL"),
    ("expected_monthly_units", "REAL"),
    ("expected_monthly_contribution_profit", "REAL"),
    ("rank_score", "REAL"),
    ("provisional_public_ebay", "INTEGER DEFAULT 0"),
    ("needs_official_ebay_validation", "INTEGER DEFAULT 1"),
    ("return_risk_score", "REAL"),
    ("dedupe_kept", "INTEGER DEFAULT 1"),
    ("shipping_status", "TEXT"),
    ("final_profitability", "INTEGER DEFAULT 0"),
    ("ship_p75", "REAL"),
    ("ship_quote_n", "INTEGER DEFAULT 0"),
    ("fails_expensive_destinations", "INTEGER DEFAULT 0"),
    ("failed_expensive_destinations", "TEXT"),
    ("dest_quotes_json", "TEXT"),
    ("pipeline_source", "TEXT"),
    ("cohort", "TEXT"),
    ("comparison_cohort_id", "TEXT"),
    ("map_ok", "INTEGER"),
    ("channel_ok", "INTEGER"),
    ("needs_manual_channel_review", "INTEGER"),
    # Shared measurable outcomes (research / creative / marketplace / learning)
    ("match_confidence", "TEXT"),
    ("demand_evidence_refs", "TEXT"),
    ("competition_snapshot_flags", "TEXT"),
    ("creative_version_id", "TEXT"),
    ("creative_variant", "TEXT"),
    ("asset_paths", "TEXT"),
    ("ab_assignment", "TEXT"),
    ("impressions", "REAL"),
    ("ctr", "REAL"),
    ("conversion_rate", "REAL"),
    ("sales_units", "REAL"),
    ("contribution_profit_realized", "REAL"),
    ("cancellations", "INTEGER"),
    ("returns", "INTEGER"),
    ("time_to_first_sale", "REAL"),
    ("sell_through", "REAL"),
    ("listing_status", "TEXT"),
    ("order_status", "TEXT"),
    ("image_urls", "TEXT"),
    ("image_count", "INTEGER DEFAULT 0"),
    ("images_fetched_at", "TEXT"),
    ("supplier_image_urls", "TEXT"),
    ("supplier_image_local_paths", "TEXT"),
]


RANKED_QUEUE_COLUMN_MIGRATIONS: list[tuple[str, str]] = [
    ("ship_p75", "REAL"),
    ("shipping_status", "TEXT"),
    ("fails_expensive_destinations", "INTEGER DEFAULT 0"),
    ("failed_expensive_destinations", "TEXT"),
    ("pipeline_source", "TEXT"),
    ("cohort", "TEXT"),
    ("comparison_cohort_id", "TEXT"),
]

CANDIDATE_COHORTS_COLUMN_MIGRATIONS: list[tuple[str, str]] = [
    ("impressions", "REAL"),
    ("ctr", "REAL"),
    ("conversion_rate", "REAL"),
    ("sales_units", "REAL"),
    ("match_confidence", "TEXT"),
    ("creative_version_id", "TEXT"),
    ("creative_variant", "TEXT"),
    ("ab_assignment", "TEXT"),
]


def connect(
    db_path: Path | str,
    *,
    timeout: float = 30.0,
    busy_timeout_ms: int = 30_000,
) -> sqlite3.Connection:
    """Open SQLite with row_factory, FKs, and busy wait (avoids silent lock races)."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=float(timeout))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)};")
    return conn


def _existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(r[1]) for r in rows}


def migrate_schema(conn: sqlite3.Connection) -> list[str]:
    """Apply additive migrations; return list of ALTER statements run."""
    applied: list[str] = []
    cols = _existing_columns(conn, "products")
    for name, decl in PRODUCT_COLUMN_MIGRATIONS:
        if name not in cols:
            ddl = f"ALTER TABLE products ADD COLUMN {name} {decl}"
            conn.execute(ddl)
            applied.append(ddl)
    if "eligible" in _existing_columns(conn, "products") and "score_pass" in _existing_columns(
        conn, "products"
    ):
        conn.execute(
            """
            UPDATE products
            SET eligible = CASE
                WHEN score_pass = 1 AND IFNULL(paused, 0) = 0 THEN 1
                ELSE 0
            END
            """
        )
    conn.executescript(EBAY_COMPETITION_DDL)
    conn.executescript(RANKED_QUEUE_DDL)
    conn.executescript(SHIPPING_QUOTES_DDL)
    conn.executescript(CANDIDATE_COHORTS_DDL)
    conn.executescript(QUARANTINE_UNRESOLVED_DDL)
    conn.executescript(OPS_EXCEPTIONS_DDL)
    rq_cols = _existing_columns(conn, "ranked_queue")
    for name, decl in RANKED_QUEUE_COLUMN_MIGRATIONS:
        if name not in rq_cols:
            ddl = f"ALTER TABLE ranked_queue ADD COLUMN {name} {decl}"
            conn.execute(ddl)
            applied.append(ddl)
    cc_cols = _existing_columns(conn, "candidate_cohorts")
    for name, decl in CANDIDATE_COHORTS_COLUMN_MIGRATIONS:
        if name not in cc_cols:
            ddl = f"ALTER TABLE candidate_cohorts ADD COLUMN {name} {decl}"
            conn.execute(ddl)
            applied.append(ddl)
    for ddl in INDEXES_DDL:
        conn.execute(ddl)
    conn.commit()
    return applied


def init_db(db_path: Path | str) -> sqlite3.Connection:
    conn = connect(db_path)
    conn.executescript(PRODUCTS_DDL)
    conn.executescript(ACTIONS_DDL)
    conn.executescript(EBAY_COMPETITION_DDL)
    conn.executescript(RANKED_QUEUE_DDL)
    conn.executescript(SHIPPING_QUOTES_DDL)
    conn.executescript(CANDIDATE_COHORTS_DDL)
    conn.executescript(QUARANTINE_UNRESOLVED_DDL)
    conn.executescript(OPS_EXCEPTIONS_DDL)
    # Migrate additive columns BEFORE indexes that reference them (eligible, etc.)
    migrate_schema(conn)
    conn.commit()
    return conn

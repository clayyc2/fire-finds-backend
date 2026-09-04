"""Split finally-profitable ranked queue into SAFE / SENSITIVE / quarantine."""

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path
from typing import Any

from firefinds.config import Settings, get_settings
from firefinds.db.schema import init_db
from firefinds.pipelines.tags import (
    COHORT_DESTINATION_SENSITIVE,
    COHORT_QUARANTINE_UNRESOLVED,
    COHORT_SAFE_NATIONWIDE,
    PIPELINE_RANDMAR_FIRST,
    tag_candidate,
)

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
    detail_json TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (sku, pipeline_source, snapshot_id)
);
"""

QUARANTINE_DDL = """
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


def ensure_cohort_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(CANDIDATE_COHORTS_DDL)
    conn.executescript(QUARANTINE_DDL)
    conn.commit()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    # Stable column union
    fieldnames: list[str] = []
    seen: set[str] = set()
    for r in rows:
        for k in r.keys():
            if k not in seen:
                seen.add(k)
                fieldnames.append(k)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k) for k in fieldnames})


def split_randmar_cohorts(
    *,
    settings: Settings | None = None,
    snapshot_id: str,
    export_dir: Path | None = None,
) -> dict[str, Any]:
    """Split ranked_queue into SAFE_NATIONWIDE / DESTINATION_SENSITIVE.

    Quarantines ALL products with shipping_status=UNRESOLVED into
    quarantine_unresolved_shipping (excluded from sellable cohorts).
    """
    settings = settings or get_settings()
    data_dir = Path(settings.db_path).parent
    out_dir = Path(export_dir or (data_dir / "cohorts" / snapshot_id / "randmar_first"))
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = init_db(settings.db_path)
    ensure_cohort_tables(conn)

    ranked = [
        dict(r)
        for r in conn.execute("SELECT * FROM ranked_queue ORDER BY rank ASC").fetchall()
    ]
    safe: list[dict[str, Any]] = []
    sensitive: list[dict[str, Any]] = []
    for row in ranked:
        fails = int(row.get("fails_expensive_destinations") or 0)
        if fails:
            cohort = COHORT_DESTINATION_SENSITIVE
            tagged = tag_candidate(
                row,
                pipeline_source=PIPELINE_RANDMAR_FIRST,
                cohort=cohort,
                snapshot_id=snapshot_id,
            )
            sensitive.append(tagged)
        else:
            cohort = COHORT_SAFE_NATIONWIDE
            tagged = tag_candidate(
                row,
                pipeline_source=PIPELINE_RANDMAR_FIRST,
                cohort=cohort,
                snapshot_id=snapshot_id,
            )
            safe.append(tagged)

    unresolved = [
        dict(r)
        for r in conn.execute(
            """
            SELECT sku, shipping_status, listable_pass, score, map, stock,
                   listable_reason AS reason
            FROM products
            WHERE UPPER(IFNULL(shipping_status, '')) = 'UNRESOLVED'
            ORDER BY sku
            """
        ).fetchall()
    ]
    quarantine: list[dict[str, Any]] = []
    for row in unresolved:
        tagged = tag_candidate(
            row,
            pipeline_source=PIPELINE_RANDMAR_FIRST,
            cohort=COHORT_QUARANTINE_UNRESOLVED,
            snapshot_id=snapshot_id,
        )
        tagged["reason"] = tagged.get("reason") or "shipping_unresolved"
        quarantine.append(tagged)

    # Persist DB tables (replace this snapshot's rows)
    conn.execute(
        "DELETE FROM candidate_cohorts WHERE pipeline_source=? AND snapshot_id=?",
        (PIPELINE_RANDMAR_FIRST, snapshot_id),
    )
    conn.execute(
        "DELETE FROM quarantine_unresolved_shipping WHERE pipeline_source=? AND snapshot_id=?",
        (PIPELINE_RANDMAR_FIRST, snapshot_id),
    )

    def _insert_cohort(row: dict[str, Any]) -> None:
        conn.execute(
            """
            INSERT INTO candidate_cohorts (
                sku, pipeline_source, cohort, comparison_cohort_id, snapshot_id,
                rank, fails_expensive_destinations, listable_profit, listable_margin,
                sell_comp, map, ship_p75, shipping_status,
                sell_through, time_to_first_sale, contribution_profit_realized,
                cancellations, returns, detail_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                row.get("sku"),
                row["pipeline_source"],
                row["cohort"],
                row["comparison_cohort_id"],
                snapshot_id,
                row.get("rank"),
                int(row.get("fails_expensive_destinations") or 0),
                row.get("listable_profit"),
                row.get("listable_margin"),
                row.get("sell_comp"),
                row.get("map"),
                row.get("ship_p75"),
                row.get("shipping_status"),
                row.get("sell_through"),
                row.get("time_to_first_sale"),
                row.get("contribution_profit_realized"),
                row.get("cancellations"),
                row.get("returns"),
                json.dumps(row, default=str),
            ),
        )

    for row in safe + sensitive:
        _insert_cohort(row)

    for row in quarantine:
        conn.execute(
            """
            INSERT INTO quarantine_unresolved_shipping (
                sku, pipeline_source, snapshot_id, shipping_status, listable_pass,
                score, map, stock, reason, comparison_cohort_id, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                row.get("sku"),
                PIPELINE_RANDMAR_FIRST,
                snapshot_id,
                row.get("shipping_status"),
                int(row.get("listable_pass") or 0),
                row.get("score"),
                row.get("map"),
                row.get("stock"),
                row.get("reason"),
                row.get("comparison_cohort_id"),
            ),
        )
    conn.commit()

    # Cohort-root for this snapshot (siblings: randmar_first / quarantine / ebay_demand_first)
    cohort_root = out_dir.parent  # data/cohorts/{snapshot_id}
    safe_dir = out_dir / "safe_nationwide"
    sensitive_dir = out_dir / "destination_sensitive"
    quarantine_dir = cohort_root / "quarantine_unresolved"
    for d in (safe_dir, sensitive_dir, quarantine_dir):
        d.mkdir(parents=True, exist_ok=True)

    summary = {
        "snapshot_id": snapshot_id,
        "pipeline_source": PIPELINE_RANDMAR_FIRST,
        "safe_nationwide": len(safe),
        "destination_sensitive": len(sensitive),
        "quarantine_unresolved": len(quarantine),
        "export_dir": str(out_dir),
        "queues": {
            "RANDMAR_FIRST/SAFE_NATIONWIDE": str(safe_dir),
            "RANDMAR_FIRST/DESTINATION_SENSITIVE": str(sensitive_dir),
            "QUARANTINE_UNRESOLVED": str(quarantine_dir),
            "EBAY_DEMAND_FIRST": str(cohort_root / "ebay_demand_first"),
        },
        "priority": ["SAFE_NATIONWIDE", "DESTINATION_SENSITIVE", "QUARANTINE_UNRESOLVED"],
    }

    # Flat files (backward compatible) + clearly separated queue subdirs
    _write_json(out_dir / "SAFE_NATIONWIDE.json", {"summary": summary, "rows": safe})
    _write_json(
        out_dir / "DESTINATION_SENSITIVE.json",
        {"summary": summary, "rows": sensitive},
    )
    _write_json(
        out_dir / "QUARANTINE_UNRESOLVED.json",
        {"summary": summary, "rows": quarantine},
    )
    _write_csv(out_dir / "SAFE_NATIONWIDE.csv", safe)
    _write_csv(out_dir / "DESTINATION_SENSITIVE.csv", sensitive)
    _write_csv(out_dir / "QUARANTINE_UNRESOLVED.csv", quarantine)
    _write_json(out_dir / "cohort_summary.json", summary)

    _write_json(safe_dir / "queue.json", {"summary": summary, "cohort": COHORT_SAFE_NATIONWIDE, "rows": safe})
    _write_csv(safe_dir / "queue.csv", safe)
    _write_json(safe_dir / "SUMMARY.json", {"count": len(safe), "cohort": COHORT_SAFE_NATIONWIDE, "priority": 1})

    _write_json(
        sensitive_dir / "queue.json",
        {"summary": summary, "cohort": COHORT_DESTINATION_SENSITIVE, "rows": sensitive},
    )
    _write_csv(sensitive_dir / "queue.csv", sensitive)
    _write_json(
        sensitive_dir / "SUMMARY.json",
        {"count": len(sensitive), "cohort": COHORT_DESTINATION_SENSITIVE, "priority": 2},
    )

    _write_json(
        quarantine_dir / "queue.json",
        {
            "summary": summary,
            "cohort": COHORT_QUARANTINE_UNRESOLVED,
            "pipeline_source": PIPELINE_RANDMAR_FIRST,
            "rows": quarantine,
        },
    )
    _write_csv(quarantine_dir / "queue.csv", quarantine)
    _write_json(
        quarantine_dir / "SUMMARY.json",
        {
            "count": len(quarantine),
            "cohort": COHORT_QUARANTINE_UNRESOLVED,
            "sellable": False,
            "priority": 3,
        },
    )
    # Manifest listing all separated queues for ready-to-list backlog
    _write_json(
        cohort_root / "READY_TO_LIST_QUEUES.json",
        {
            "snapshot_id": snapshot_id,
            "gates": {
                "LIVE_LISTINGS_ENABLED": False,
                "SUPPLIER_ORDERS_ENABLED": False,
                "publish": False,
            },
            "queues": summary["queues"],
            "counts": {
                "RANDMAR_FIRST/SAFE_NATIONWIDE": len(safe),
                "RANDMAR_FIRST/DESTINATION_SENSITIVE": len(sensitive),
                "QUARANTINE_UNRESOLVED": len(quarantine),
            },
            "priority_order": [
                "RANDMAR_FIRST/SAFE_NATIONWIDE",
                "RANDMAR_FIRST/DESTINATION_SENSITIVE",
                "QUARANTINE_UNRESOLVED",
                "EBAY_DEMAND_FIRST",
            ],
        },
    )

    # Mirror into snapshot dir when present
    snap_dir = data_dir / "snapshots" / f"{snapshot_id}_shipping_complete"
    if snap_dir.is_dir():
        mirror = snap_dir / "cohorts"
        mirror.mkdir(parents=True, exist_ok=True)
        for name in (
            "SAFE_NATIONWIDE.json",
            "DESTINATION_SENSITIVE.json",
            "QUARANTINE_UNRESOLVED.json",
            "cohort_summary.json",
        ):
            src = out_dir / name
            if src.is_file():
                (mirror / name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    conn.close()
    return {
        "summary": summary,
        "safe": safe,
        "sensitive": sensitive,
        "quarantine": quarantine,
    }

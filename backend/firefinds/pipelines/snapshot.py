"""Freeze an immutable shipping-complete snapshot under data/snapshots/."""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from firefinds.config import Settings, get_settings
from firefinds.db.schema import init_db
from firefinds.pipelines.tags import PIPELINE_RANDMAR_FIRST

EDMONTON = ZoneInfo("America/Edmonton")

RELEVANT_TABLES = (
    "products",
    "ranked_queue",
    "shipping_quotes",
    "ebay_competition",
    "actions",
)


def _edmonton_now() -> datetime:
    return datetime.now(EDMONTON)


def snapshot_stamp_from_progress(progress: dict[str, Any] | None) -> str:
    """Prefer progress.updated_at (Edmonton local) else current Edmonton time."""
    if progress and progress.get("updated_at"):
        raw = str(progress["updated_at"])
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return dt.astimezone(EDMONTON).strftime("%Y%m%d_%H%M")
        except ValueError:
            pass
    return _edmonton_now().strftime("%Y%m%d_%H%M")


def _dump_table(conn: sqlite3.Connection, table: str, out_path: Path) -> int:
    rows = conn.execute(f"SELECT * FROM {table}").fetchall()
    payload = [dict(r) for r in rows]
    out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return len(payload)


def freeze_shipping_snapshot(
    *,
    settings: Settings | None = None,
    snapshot_id: str | None = None,
    git_head: str | None = None,
) -> dict[str, Any]:
    """Copy progress/ranked_queue/quotes + relevant table dumps into snapshots/.

    Tags RANDMAR_FIRST on ranked_queue survivors in the snapshot metadata.
    Does not mutate live sellable state beyond optional pipeline_source columns
    when schema migrations have been applied.
    """
    settings = settings or get_settings()
    data_dir = Path(settings.db_path).parent
    progress_path = data_dir / "shipping_quote_progress.json"
    progress: dict[str, Any] = {}
    if progress_path.is_file():
        progress = json.loads(progress_path.read_text(encoding="utf-8"))

    stamp = snapshot_id or snapshot_stamp_from_progress(progress)
    snap_dir = data_dir / "snapshots" / f"{stamp}_shipping_complete"
    snap_dir.mkdir(parents=True, exist_ok=True)
    tables_dir = snap_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    # Immutable copies of run artifacts
    for name in (
        "shipping_quote_progress.json",
        "ranked_queue.json",
        "shipping_quotes.json",
        "quote_shipping_run.log",
    ):
        src = data_dir / name
        if src.is_file():
            shutil.copy2(src, snap_dir / name)

    # DB copy (full) — large but exact freeze
    db_src = Path(settings.db_path)
    if db_src.is_file():
        shutil.copy2(db_src, snap_dir / "firefinds.db")

    conn = init_db(settings.db_path)
    table_counts: dict[str, int] = {}
    for table in RELEVANT_TABLES:
        try:
            n = _dump_table(conn, table, tables_dir / f"{table}.json")
            table_counts[table] = n
        except sqlite3.Error:
            table_counts[table] = -1

    # Counts from live ranked_queue / progress
    rq = conn.execute(
        """
        SELECT COUNT(*) AS n,
               SUM(IFNULL(fails_expensive_destinations,0)) AS fed
        FROM ranked_queue
        """
    ).fetchone()
    ranked_n = int(rq["n"] or 0)
    fed_n = int(rq["fed"] or 0)
    resolved = int(progress.get("resolved_skus") or 0)
    unresolved = int(progress.get("unresolved_skus") or 0)
    if not resolved:
        resolved = conn.execute(
            "SELECT COUNT(*) FROM products WHERE shipping_status='RESOLVED'"
        ).fetchone()[0]
    if not unresolved:
        unresolved = conn.execute(
            "SELECT COUNT(*) FROM products WHERE shipping_status='UNRESOLVED'"
        ).fetchone()[0]

    # Tag pipeline_source on snapshot export of ranked queue
    ranked_export_path = snap_dir / "ranked_queue.json"
    if ranked_export_path.is_file():
        ranked = json.loads(ranked_export_path.read_text(encoding="utf-8"))
        for row in ranked.get("queue") or []:
            row["pipeline_source"] = PIPELINE_RANDMAR_FIRST
        ranked_export_path.write_text(
            json.dumps(ranked, indent=2, default=str), encoding="utf-8"
        )

    # Also write a slim candidates file tagged RANDMAR_FIRST
    candidates = [
        dict(r)
        for r in conn.execute("SELECT * FROM ranked_queue ORDER BY rank ASC").fetchall()
    ]
    for c in candidates:
        c["pipeline_source"] = PIPELINE_RANDMAR_FIRST
    (snap_dir / "candidates_randmar_first.json").write_text(
        json.dumps(candidates, indent=2, default=str), encoding="utf-8"
    )

    now_ed = _edmonton_now()
    meta = {
        "snapshot_id": stamp,
        "snapshot_dir": str(snap_dir),
        "frozen_at_america_edmonton": now_ed.replace(microsecond=0).isoformat(),
        "frozen_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z'),
        "timezone": "America/Edmonton",
        "git_head": git_head,
        "pipeline_source": PIPELINE_RANDMAR_FIRST,
        "counts": {
            "resolved_skus": resolved,
            "unresolved_skus": unresolved,
            "finally_profitable": ranked_n,
            "fails_expensive_destinations": fed_n,
            "safe_nationwide_expected": ranked_n - fed_n,
            "destination_sensitive_expected": fed_n,
        },
        "source_progress": progress,
        "table_counts": table_counts,
        "files": [],
    }
    meta_path = snap_dir / "freeze_metadata.json"
    meta_path.write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
    meta["files"] = sorted(p.name for p in snap_dir.iterdir() if p.is_file())
    meta_path.write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
    conn.close()
    return meta

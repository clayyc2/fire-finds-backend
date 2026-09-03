"""Append-only action logger: every decision to JSONL and SQLite."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class ActionLogger:
    """Logs decisions to JSONL and the `actions` SQLite table."""

    def __init__(
        self,
        jsonl_path: Path | str,
        db_path: Path | str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        self.jsonl_path = Path(jsonl_path)
        self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        self._owns_conn = False
        if conn is not None:
            self.conn = conn
        elif db_path is not None:
            from firefinds.db.schema import init_db

            self.conn = init_db(db_path)
            self._owns_conn = True
        else:
            self.conn = None

    def log(
        self,
        action: str,
        *,
        sku: str | None = None,
        decision: str | None = None,
        detail: Mapping[str, Any] | None = None,
        source: str | None = None,
    ) -> dict[str, Any]:
        # Never accept or echo fields that look like secrets
        safe_detail = dict(detail or {})
        for key in list(safe_detail.keys()):
            lk = key.lower()
            if any(
                s in lk
                for s in ("secret", "password", "token", "client_secret")
            ):
                safe_detail[key] = "[redacted]"

        record = {
            "ts": _utc_now_iso(),
            "action": action,
            "sku": sku,
            "decision": decision,
            "detail": safe_detail,
            "source": source,
        }

        with self.jsonl_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")

        if self.conn is not None:
            self.conn.execute(
                """
                INSERT INTO actions (ts, action, sku, decision, detail_json, source)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    record["ts"],
                    action,
                    sku,
                    decision,
                    json.dumps(safe_detail, default=str),
                    source,
                ),
            )
            self.conn.commit()

        return record

    def close(self) -> None:
        if self._owns_conn and self.conn is not None:
            self.conn.close()
            self.conn = None

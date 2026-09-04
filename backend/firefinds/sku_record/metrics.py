"""Upsert / export helpers for shared SKU measurable outcomes."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from firefinds.config import Settings, get_settings
from firefinds.db.schema import init_db
from firefinds.sku_record.constants import (
    ALL_MEASURABLE_KEYS,
    CREATIVE_VARIANTS,
    JSON_METRIC_KEYS,
    MATCH_CONFIDENCE_VALUES,
    PIPELINE_SOURCES,
)

_ALLOWED = frozenset(ALL_MEASURABLE_KEYS)


def _encode_value(key: str, value: Any) -> Any:
    if value is None:
        return None
    if key in JSON_METRIC_KEYS:
        if isinstance(value, (dict, list, tuple)):
            return json.dumps(value, default=str)
        if isinstance(value, str):
            # Accept already-serialized JSON or plain string refs
            return value
        return json.dumps(value, default=str)
    return value


def _decode_row(row: Mapping[str, Any] | sqlite3.Row) -> dict[str, Any]:
    out = dict(row)
    for key in JSON_METRIC_KEYS:
        raw = out.get(key)
        if isinstance(raw, str) and raw.strip():
            try:
                out[key] = json.loads(raw)
            except json.JSONDecodeError:
                pass
    return out


def _validate_metrics(metrics: Mapping[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(metrics) - _ALLOWED)
    if unknown:
        raise ValueError(f"unknown measurable keys: {unknown}")
    cleaned: dict[str, Any] = {}
    for key, value in metrics.items():
        if key not in _ALLOWED:
            continue
        if value is None:
            cleaned[key] = None
            continue
        if key == "pipeline_source" and str(value) not in PIPELINE_SOURCES:
            raise ValueError(
                f"pipeline_source must be one of {sorted(PIPELINE_SOURCES)}"
            )
        if key == "match_confidence" and str(value) not in MATCH_CONFIDENCE_VALUES:
            raise ValueError(
                f"match_confidence must be one of {sorted(MATCH_CONFIDENCE_VALUES)}"
            )
        if key == "creative_variant" and str(value) not in CREATIVE_VARIANTS:
            raise ValueError(
                f"creative_variant must be one of {sorted(CREATIVE_VARIANTS)}"
            )
        cleaned[key] = value
    return cleaned


def upsert_sku_metrics(
    sku: str,
    metrics: Mapping[str, Any],
    *,
    settings: Settings | None = None,
    conn: sqlite3.Connection | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """Write measurable outcome fields onto the shared products SKU row.

    Only keys in ALL_MEASURABLE_KEYS are accepted. JSON list/dict fields are
    stored as TEXT. Returns the updated measurable slice of the SKU record.
    """
    settings = settings or get_settings()
    cleaned = _validate_metrics(metrics)
    if not cleaned:
        raise ValueError("no measurable metrics provided")

    owns = conn is None
    db = conn or init_db(settings.db_path)
    try:
        existing = db.execute(
            "SELECT sku FROM products WHERE sku=?", (sku,)
        ).fetchone()
        if existing is None:
            db.execute(
                """
                INSERT INTO products (sku, created_at, updated_at)
                VALUES (?, datetime('now'), datetime('now'))
                """,
                (sku,),
            )

        cols = []
        vals: list[Any] = []
        for key, value in cleaned.items():
            cols.append(f"{key}=?")
            vals.append(_encode_value(key, value))
        cols.append("updated_at=datetime('now')")
        sql = f"UPDATE products SET {', '.join(cols)} WHERE sku=?"
        vals.append(sku)
        db.execute(sql, vals)
        db.commit()

        from firefinds.action_log.logger import ActionLogger

        # Pass our open conn (ActionLogger only closes when it opened the DB).
        ActionLogger(settings.actions_jsonl, conn=db).log(
            "sku_metrics_upsert",
            sku=sku,
            decision="updated",
            detail={"keys": sorted(cleaned.keys()), "source": source},
            source=source or "sku_record",
        )

        return get_sku_record(sku, settings=settings, conn=db)
    finally:
        if owns:
            db.close()


def get_sku_record(
    sku: str,
    *,
    settings: Settings | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Return core product fields + measurable outcomes for a SKU."""
    settings = settings or get_settings()
    owns = conn is None
    db = conn or init_db(settings.db_path)
    try:
        row = db.execute("SELECT * FROM products WHERE sku=?", (sku,)).fetchone()
        if row is None:
            raise KeyError(f"sku not found: {sku}")
        decoded = _decode_row(row)
        measurable = {k: decoded.get(k) for k in ALL_MEASURABLE_KEYS}
        return {
            "sku": sku,
            "title": decoded.get("title"),
            "manufacturer": decoded.get("manufacturer"),
            "mpn": decoded.get("mpn"),
            "map": decoded.get("map"),
            "stock": decoded.get("stock"),
            "shipping_status": decoded.get("shipping_status"),
            "listable_pass": decoded.get("listable_pass"),
            "listable_profit": decoded.get("listable_profit"),
            "listable_margin": decoded.get("listable_margin"),
            "sell_comp": decoded.get("sell_comp"),
            "ship_p75": decoded.get("ship_p75"),
            "cohort": decoded.get("cohort"),
            "map_ok": decoded.get("map_ok"),
            "channel_ok": decoded.get("channel_ok"),
            "opportunity_only": decoded.get("opportunity_only"),
            "paused": decoded.get("paused"),
            "metrics": measurable,
            "record": decoded,
        }
    finally:
        if owns:
            db.close()


def export_learning_comparison(
    *,
    settings: Settings | None = None,
    comparison_cohort_id: str | None = None,
    pipeline_source: str | None = None,
    limit: int | None = None,
    export_path: Path | str | None = None,
) -> dict[str, Any]:
    """Export SKUs with measurable outcomes for pipeline/creative A/B learning.

    Filters optionally by comparison_cohort_id and/or pipeline_source.
    Writes JSON when export_path is set.
    """
    settings = settings or get_settings()
    conn = init_db(settings.db_path)
    try:
        where: list[str] = []
        params: list[Any] = []
        if comparison_cohort_id:
            where.append("comparison_cohort_id = ?")
            params.append(comparison_cohort_id)
        if pipeline_source:
            where.append("pipeline_source = ?")
            params.append(pipeline_source)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        sql = f"""
            SELECT sku, pipeline_source, match_confidence, demand_evidence_refs,
                   competition_snapshot_flags, creative_version_id, creative_variant,
                   asset_paths, ab_assignment, comparison_cohort_id,
                   impressions, ctr, conversion_rate, sales_units,
                   contribution_profit_realized, cancellations, returns,
                   time_to_first_sale, sell_through, listing_status, order_status,
                   cohort, shipping_status, listable_profit, listable_margin,
                   sell_comp, map, stock, rank_score
            FROM products
            {clause}
            ORDER BY IFNULL(rank_score, 0) DESC, sku
        """
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        rows = [_decode_row(r) for r in conn.execute(sql, params).fetchall()]
        payload = {
            "count": len(rows),
            "filters": {
                "comparison_cohort_id": comparison_cohort_id,
                "pipeline_source": pipeline_source,
                "limit": limit,
            },
            "rows": rows,
        }
        if export_path is not None:
            path = Path(export_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(payload, indent=2, default=str), encoding="utf-8"
            )
            payload["export_path"] = str(path)
        return payload
    finally:
        conn.close()

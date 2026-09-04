"""Deterministic Ops exception rules — auto-flag / pause candidates.

No AI improvisation: each rule is a pure predicate over SKU / product fields
(and, for API ingest streak, the actions log). Hits persist to `ops_exceptions`
and `actions` (action_log); products are paused when a rule fires.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

from firefinds.action_log.logger import ActionLogger
from firefinds.config import Settings, get_settings
from firefinds.db.schema import init_db

# Stable rule codes (never rename lightly — persisted on rows).
RULE_STOCK_LEQ_BUFFER = "STOCK_LEQ_BUFFER"
RULE_SHIPPING_UNRESOLVED = "SHIPPING_UNRESOLVED"
RULE_PROFIT_BELOW_MIN = "PROFIT_BELOW_MIN"
RULE_MARGIN_BELOW_MIN = "MARGIN_BELOW_MIN"
RULE_MAP_BREACH = "MAP_BREACH"
RULE_CHANNEL_AUTH_FAIL = "CHANNEL_AUTH_FAIL"
RULE_API_INGEST_FAILURE_STREAK = "API_INGEST_FAILURE_STREAK"

SEVERITY_PAUSE = "pause"
SEVERITY_FLAG = "flag"

DEFAULT_INGEST_STREAK_THRESHOLD = 3
GLOBAL_INGEST_SKU = "__INGEST__"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _f(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _i(value: Any, default: int | None = None) -> int | None:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _truthy_int(value: Any) -> bool | None:
    """Return True/False for 0/1-ish, None if unknown/missing."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    try:
        return int(value) == 1
    except (TypeError, ValueError):
        return bool(value)


@dataclass(frozen=True)
class RuleHit:
    rule_code: str
    severity: str
    message: str
    detail: dict[str, Any]


@dataclass(frozen=True)
class ExceptionRule:
    code: str
    description: str
    severity: str
    evaluate: Callable[[Mapping[str, Any], Settings], RuleHit | None]


def _eval_stock(row: Mapping[str, Any], settings: Settings) -> RuleHit | None:
    stock = _i(row.get("stock"), 0) or 0
    buffer = int(settings.stock_buffer)
    if stock <= buffer:
        return RuleHit(
            RULE_STOCK_LEQ_BUFFER,
            SEVERITY_PAUSE,
            f"stock {stock} <= buffer {buffer}",
            {"stock": stock, "stock_buffer": buffer},
        )
    return None


def _eval_shipping(row: Mapping[str, Any], settings: Settings) -> RuleHit | None:
    status = str(row.get("shipping_status") or "").strip().upper()
    if status == "UNRESOLVED":
        return RuleHit(
            RULE_SHIPPING_UNRESOLVED,
            SEVERITY_PAUSE,
            "shipping_status is UNRESOLVED",
            {"shipping_status": status},
        )
    return None


def _profit_value(row: Mapping[str, Any]) -> float | None:
    for key in ("listable_profit", "contribution_profit"):
        v = _f(row.get(key))
        if v is not None:
            return v
    return None


def _margin_value(row: Mapping[str, Any]) -> float | None:
    for key in ("listable_margin", "contribution_margin"):
        v = _f(row.get(key))
        if v is not None:
            return v
    return None


def _eval_profit(row: Mapping[str, Any], settings: Settings) -> RuleHit | None:
    profit = _profit_value(row)
    if profit is None:
        return None
    floor = float(settings.min_contribution_profit_cad)
    if profit < floor:
        return RuleHit(
            RULE_PROFIT_BELOW_MIN,
            SEVERITY_PAUSE,
            f"contribution profit {profit:.4f} < {floor} CAD",
            {"profit": profit, "min_contribution_profit_cad": floor},
        )
    return None


def _eval_margin(row: Mapping[str, Any], settings: Settings) -> RuleHit | None:
    margin = _margin_value(row)
    if margin is None:
        return None
    floor = float(settings.min_contribution_margin)
    if margin < floor:
        return RuleHit(
            RULE_MARGIN_BELOW_MIN,
            SEVERITY_PAUSE,
            f"contribution margin {margin:.4f} < {floor}",
            {"margin": margin, "min_contribution_margin": floor},
        )
    return None


def _eval_map_breach(row: Mapping[str, Any], settings: Settings) -> RuleHit | None:
    map_price = _f(row.get("map"), 0.0) or 0.0
    if map_price <= 0:
        return None
    # Prefer explicit sell; fall back to sell_comp / listable context.
    price = None
    for key in ("sell_price", "sell_comp", "listable_sell"):
        if row.get(key) is not None:
            price = _f(row.get(key))
            break
    if price is None:
        map_ok = _truthy_int(row.get("map_ok"))
        if map_ok is False:
            return RuleHit(
                RULE_MAP_BREACH,
                SEVERITY_PAUSE,
                "map_ok=0 (MAP breach flagged)",
                {"map": map_price, "map_ok": 0},
            )
        return None
    if price + 1e-9 < map_price:
        return RuleHit(
            RULE_MAP_BREACH,
            SEVERITY_PAUSE,
            f"price {price:.4f} < MAP {map_price:.4f}",
            {"price": price, "map": map_price},
        )
    return None


def _eval_channel_auth(row: Mapping[str, Any], settings: Settings) -> RuleHit | None:
    channel_ok = _truthy_int(row.get("channel_ok"))
    map_ok = _truthy_int(row.get("map_ok"))
    opportunity_only = bool(row.get("opportunity_only"))
    reasons: list[str] = []
    detail: dict[str, Any] = {}
    if channel_ok is False:
        reasons.append("channel_ok=0")
        detail["channel_ok"] = 0
    if map_ok is False:
        reasons.append("map_ok=0")
        detail["map_ok"] = 0
    if opportunity_only and channel_ok is not True:
        # opportunity_only implies channel restriction even if channel_ok unset
        if "channel_ok=0" not in reasons:
            reasons.append("opportunity_only")
        detail["opportunity_only"] = True
    if not reasons:
        return None
    return RuleHit(
        RULE_CHANNEL_AUTH_FAIL,
        SEVERITY_PAUSE,
        "channel/authorization fail: " + ", ".join(reasons),
        detail,
    )


EXCEPTION_RULES: tuple[ExceptionRule, ...] = (
    ExceptionRule(
        RULE_STOCK_LEQ_BUFFER,
        "stock ≤ stock_buffer",
        SEVERITY_PAUSE,
        _eval_stock,
    ),
    ExceptionRule(
        RULE_SHIPPING_UNRESOLVED,
        "shipping_status becomes UNRESOLVED",
        SEVERITY_PAUSE,
        _eval_shipping,
    ),
    ExceptionRule(
        RULE_PROFIT_BELOW_MIN,
        "contribution profit < min CAD ($8 default)",
        SEVERITY_PAUSE,
        _eval_profit,
    ),
    ExceptionRule(
        RULE_MARGIN_BELOW_MIN,
        "contribution margin < min (12% default)",
        SEVERITY_PAUSE,
        _eval_margin,
    ),
    ExceptionRule(
        RULE_MAP_BREACH,
        "price < MAP (MAP breach)",
        SEVERITY_PAUSE,
        _eval_map_breach,
    ),
    ExceptionRule(
        RULE_CHANNEL_AUTH_FAIL,
        "channel / authorization fail",
        SEVERITY_PAUSE,
        _eval_channel_auth,
    ),
)


def evaluate_candidate(
    row: Mapping[str, Any],
    settings: Settings | None = None,
    *,
    rules: Sequence[ExceptionRule] | None = None,
) -> list[RuleHit]:
    """Evaluate deterministic per-SKU rules; return all hits (no side effects)."""
    settings = settings or get_settings()
    active = rules if rules is not None else EXCEPTION_RULES
    hits: list[RuleHit] = []
    for rule in active:
        hit = rule.evaluate(row, settings)
        if hit is not None:
            hits.append(hit)
    return hits


def ingest_failure_streak(
    conn: sqlite3.Connection,
    *,
    threshold: int = DEFAULT_INGEST_STREAK_THRESHOLD,
) -> RuleHit | None:
    """Count trailing consecutive ingest failures from the actions table.

    Looks at recent rows where action IN ('ingest','ingest-live','ingest-stub')
    ordered by ts DESC, id DESC. A failure is decision in
    {fail, failed, error, refused} or starting with 'fail'/'error'.
    """
    rows = conn.execute(
        """
        SELECT action, decision, ts
        FROM actions
        WHERE action IN ('ingest', 'ingest-live', 'ingest-stub', 'api_ingest')
        ORDER BY ts DESC, id DESC
        LIMIT 50
        """
    ).fetchall()
    streak = 0
    for row in rows:
        decision = str(row["decision"] or "").strip().lower()
        is_fail = decision in {"fail", "failed", "error", "refused"} or decision.startswith(
            "fail"
        ) or decision.startswith("error")
        if is_fail:
            streak += 1
        else:
            break
    if streak >= int(threshold):
        return RuleHit(
            RULE_API_INGEST_FAILURE_STREAK,
            SEVERITY_FLAG,
            f"API ingest failure streak {streak} >= {threshold}",
            {"streak": streak, "threshold": threshold},
        )
    return None


def _upsert_exception(
    conn: sqlite3.Connection,
    *,
    sku: str,
    rule_code: str,
    severity: str,
    status: str,
    message: str,
    detail: Mapping[str, Any],
    snapshot_id: str | None,
    pipeline_source: str | None,
    cohort: str | None,
) -> str:
    """Insert or refresh an open exception; return 'created' or 'updated'."""
    now = _utc_now()
    existing = conn.execute(
        """
        SELECT id, status FROM ops_exceptions
        WHERE sku = ? AND rule_code = ? AND status IN ('open', 'paused')
        ORDER BY id DESC LIMIT 1
        """,
        (sku, rule_code),
    ).fetchone()
    detail_json = json.dumps(dict(detail), default=str)
    if existing:
        conn.execute(
            """
            UPDATE ops_exceptions
            SET severity=?, status=?, message=?, detail_json=?,
                snapshot_id=COALESCE(?, snapshot_id),
                pipeline_source=COALESCE(?, pipeline_source),
                cohort=COALESCE(?, cohort),
                updated_at=?,
                resolved_at=NULL
            WHERE id=?
            """,
            (
                severity,
                status,
                message,
                detail_json,
                snapshot_id,
                pipeline_source,
                cohort,
                now,
                existing["id"],
            ),
        )
        return "updated"
    conn.execute(
        """
        INSERT INTO ops_exceptions (
            sku, rule_code, severity, status, message, detail_json,
            snapshot_id, pipeline_source, cohort, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            sku,
            rule_code,
            severity,
            status,
            message,
            detail_json,
            snapshot_id,
            pipeline_source,
            cohort,
            now,
            now,
        ),
    )
    return "created"


def _pause_product(
    conn: sqlite3.Connection,
    sku: str,
    reason: str,
) -> None:
    if sku == GLOBAL_INGEST_SKU:
        return
    conn.execute(
        """
        UPDATE products
        SET paused=1,
            pause_reason=?,
            eligible=0,
            updated_at=datetime('now')
        WHERE sku=?
        """,
        (reason[:500], sku),
    )


def _load_scan_rows(
    conn: sqlite3.Connection,
    *,
    snapshot_id: str | None,
    limit: int | None,
) -> list[dict[str, Any]]:
    """Candidates + simulated listings: cohort rows joined to products when present."""
    sql = """
        SELECT
            COALESCE(c.sku, p.sku) AS sku,
            p.stock AS stock,
            COALESCE(p.shipping_status, c.shipping_status) AS shipping_status,
            COALESCE(p.listable_profit, c.listable_profit, p.contribution_profit)
                AS listable_profit,
            COALESCE(p.listable_margin, c.listable_margin, p.contribution_margin)
                AS listable_margin,
            p.contribution_profit AS contribution_profit,
            p.contribution_margin AS contribution_margin,
            COALESCE(p.map, c.map) AS map,
            p.sell_comp AS sell_comp,
            p.map_ok AS map_ok,
            p.channel_ok AS channel_ok,
            p.opportunity_only AS opportunity_only,
            p.paused AS paused,
            p.pause_reason AS pause_reason,
            p.listing_status AS listing_status,
            c.pipeline_source AS pipeline_source,
            c.cohort AS cohort,
            c.snapshot_id AS snapshot_id,
            c.rank AS rank
        FROM candidate_cohorts c
        LEFT JOIN products p ON p.sku = c.sku
        WHERE 1=1
    """
    params: list[Any] = []
    if snapshot_id:
        sql += " AND c.snapshot_id = ?"
        params.append(snapshot_id)
    sql += " ORDER BY IFNULL(c.rank, 999999), c.sku"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]

    # Also include simulated listings not in cohorts (dry-run / SIMULATED_*)
    sim_sql = """
        SELECT
            p.sku AS sku,
            p.stock AS stock,
            p.shipping_status AS shipping_status,
            COALESCE(p.listable_profit, p.contribution_profit) AS listable_profit,
            COALESCE(p.listable_margin, p.contribution_margin) AS listable_margin,
            p.contribution_profit AS contribution_profit,
            p.contribution_margin AS contribution_margin,
            p.map AS map,
            p.sell_comp AS sell_comp,
            p.map_ok AS map_ok,
            p.channel_ok AS channel_ok,
            p.opportunity_only AS opportunity_only,
            p.paused AS paused,
            p.pause_reason AS pause_reason,
            p.listing_status AS listing_status,
            p.pipeline_source AS pipeline_source,
            p.cohort AS cohort,
            NULL AS snapshot_id,
            p.listable_rank AS rank
        FROM products p
        WHERE (
            IFNULL(p.listing_status, '') LIKE 'SIMULATED%'
            OR IFNULL(p.order_status, '') LIKE 'SIMULATED%'
        )
    """
    if rows:
        seen = {r["sku"] for r in rows}
        sim_sql += " AND p.sku NOT IN ({})".format(
            ",".join("?" for _ in seen)
        )
        sim_params: list[Any] = list(seen)
    else:
        sim_params = []
    if limit is not None:
        remaining = max(0, int(limit) - len(rows))
        sim_sql += " LIMIT ?"
        sim_params.append(remaining)
    for r in conn.execute(sim_sql, sim_params).fetchall():
        rows.append(dict(r))
    return rows


def _is_db_locked(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return isinstance(exc, sqlite3.OperationalError) and (
        "locked" in msg or "busy" in msg
    )


def scan_exceptions(
    *,
    settings: Settings | None = None,
    snapshot_id: str | None = None,
    limit: int | None = None,
    ingest_streak_threshold: int = DEFAULT_INGEST_STREAK_THRESHOLD,
    apply_pause: bool = True,
    conn: sqlite3.Connection | None = None,
    lock_retries: int = 8,
    lock_retry_sleep_sec: float = 0.75,
) -> dict[str, Any]:
    """Scan candidates / simulated listings; persist exceptions + action_log.

    Retries on SQLite lock/busy (e.g. concurrent image backfill) using connect()'s
    busy_timeout plus a short outer backoff — avoids silent empty/zero summaries.
    """
    settings = settings or get_settings()
    owns = conn is None
    last_err: BaseException | None = None
    for attempt in range(max(1, int(lock_retries))):
        try:
            if owns:
                conn = init_db(settings.db_path)
            assert conn is not None
            return _scan_exceptions_once(
                conn=conn,
                owns=owns,
                settings=settings,
                snapshot_id=snapshot_id,
                limit=limit,
                ingest_streak_threshold=ingest_streak_threshold,
                apply_pause=apply_pause,
            )
        except sqlite3.OperationalError as exc:
            last_err = exc
            if owns and conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
                conn = None
            if not _is_db_locked(exc) or attempt >= int(lock_retries) - 1:
                raise
            time.sleep(float(lock_retry_sleep_sec) * (attempt + 1))
    assert last_err is not None
    raise last_err


def _scan_exceptions_once(
    *,
    conn: sqlite3.Connection,
    owns: bool,
    settings: Settings,
    snapshot_id: str | None,
    limit: int | None,
    ingest_streak_threshold: int,
    apply_pause: bool,
) -> dict[str, Any]:
    logger = ActionLogger(settings.actions_jsonl, conn=conn)

    rows = _load_scan_rows(conn, snapshot_id=snapshot_id, limit=limit)
    created = 0
    updated = 0
    paused_skus: set[str] = set()
    hits_by_rule: dict[str, int] = {r.code: 0 for r in EXCEPTION_RULES}
    hits_by_rule[RULE_API_INGEST_FAILURE_STREAK] = 0
    scanned = 0

    for row in rows:
        scanned += 1
        sku = str(row.get("sku") or "")
        if not sku:
            continue
        hits = evaluate_candidate(row, settings)
        if not hits:
            continue
        pause_reasons: list[str] = []
        for hit in hits:
            hits_by_rule[hit.rule_code] = hits_by_rule.get(hit.rule_code, 0) + 1
            status = "paused" if hit.severity == SEVERITY_PAUSE else "open"
            outcome = _upsert_exception(
                conn,
                sku=sku,
                rule_code=hit.rule_code,
                severity=hit.severity,
                status=status,
                message=hit.message,
                detail=hit.detail,
                snapshot_id=row.get("snapshot_id") or snapshot_id,
                pipeline_source=row.get("pipeline_source"),
                cohort=row.get("cohort"),
            )
            if outcome == "created":
                created += 1
            else:
                updated += 1
            logger.log(
                "ops_exception",
                sku=sku,
                decision=hit.rule_code,
                detail={
                    "severity": hit.severity,
                    "message": hit.message,
                    "status": status,
                    **hit.detail,
                },
                source="ops.exceptions.scan",
            )
            if hit.severity == SEVERITY_PAUSE:
                pause_reasons.append(f"{hit.rule_code}: {hit.message}")
        if apply_pause and pause_reasons:
            reason = "; ".join(pause_reasons)
            _pause_product(conn, sku, reason)
            paused_skus.add(sku)
            logger.log(
                "ops_pause",
                sku=sku,
                decision="paused",
                detail={"pause_reason": reason},
                source="ops.exceptions.scan",
            )

    # Global ingest streak rule
    streak_hit = ingest_failure_streak(conn, threshold=ingest_streak_threshold)
    if streak_hit is not None:
        hits_by_rule[RULE_API_INGEST_FAILURE_STREAK] = 1
        outcome = _upsert_exception(
            conn,
            sku=GLOBAL_INGEST_SKU,
            rule_code=streak_hit.rule_code,
            severity=streak_hit.severity,
            status="open",
            message=streak_hit.message,
            detail=streak_hit.detail,
            snapshot_id=snapshot_id,
            pipeline_source=None,
            cohort=None,
        )
        if outcome == "created":
            created += 1
        else:
            updated += 1
        logger.log(
            "ops_exception",
            sku=GLOBAL_INGEST_SKU,
            decision=streak_hit.rule_code,
            detail={
                "severity": streak_hit.severity,
                "message": streak_hit.message,
                **streak_hit.detail,
            },
            source="ops.exceptions.scan",
        )

    conn.commit()
    summary = {
        "scanned": scanned,
        "created": created,
        "updated": updated,
        "paused_skus": sorted(paused_skus),
        "paused_count": len(paused_skus),
        "hits_by_rule": hits_by_rule,
        "snapshot_id": snapshot_id,
        "ingest_streak_threshold": ingest_streak_threshold,
        "finished_at": _utc_now(),
    }
    if owns:
        conn.close()
    return summary


def list_exceptions(
    *,
    settings: Settings | None = None,
    status: str | None = "open,paused",
    rule_code: str | None = None,
    sku: str | None = None,
    limit: int | None = 100,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """List persisted ops_exceptions rows (newest first)."""
    settings = settings or get_settings()
    owns = conn is None
    conn = conn or init_db(settings.db_path)
    sql = "SELECT * FROM ops_exceptions WHERE 1=1"
    params: list[Any] = []
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if statuses:
            sql += " AND status IN ({})".format(",".join("?" for _ in statuses))
            params.extend(statuses)
    if rule_code:
        sql += " AND rule_code = ?"
        params.append(rule_code)
    if sku:
        sql += " AND sku = ?"
        params.append(sku)
    sql += " ORDER BY updated_at DESC, id DESC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))
    out = [dict(r) for r in conn.execute(sql, params).fetchall()]
    if owns:
        conn.close()
    return out


def rule_catalog() -> list[dict[str, str]]:
    """Human-readable rule list for docs / CLI help."""
    rows = [
        {"code": r.code, "description": r.description, "severity": r.severity}
        for r in EXCEPTION_RULES
    ]
    rows.append(
        {
            "code": RULE_API_INGEST_FAILURE_STREAK,
            "description": (
                f"trailing ingest failures in actions >= "
                f"{DEFAULT_INGEST_STREAK_THRESHOLD}"
            ),
            "severity": SEVERITY_FLAG,
        }
    )
    return rows

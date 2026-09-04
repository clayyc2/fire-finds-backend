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
RULE_COST_SPIKE = "COST_SPIKE"
RULE_RETURNS_RATE_HIGH = "RETURNS_RATE_HIGH"
RULE_CANCELLATION_RATE_HIGH = "CANCELLATION_RATE_HIGH"
RULE_CS_EXCEPTION_OPEN = "CS_EXCEPTION_OPEN"
RULE_ACCOUNT_HEALTH_RISK = "ACCOUNT_HEALTH_RISK"
RULE_TRACKING_MISSING = "TRACKING_MISSING"
RULE_FULFILLMENT_LATE = "FULFILLMENT_LATE"
RULE_DUPLICATE_LISTING = "DUPLICATE_LISTING"
RULE_INVALID_LISTING = "INVALID_LISTING"

SEVERITY_PAUSE = "pause"
SEVERITY_FLAG = "flag"

DEFAULT_INGEST_STREAK_THRESHOLD = 3
GLOBAL_INGEST_SKU = "__INGEST__"
GLOBAL_ACCOUNT_SKU = "__ACCOUNT__"

# Unlock / CS / fulfillment thresholds (deterministic; gates stay OFF).
DEFAULT_COST_SPIKE_PCT = 0.10
DEFAULT_RETURNS_RATE_MAX = 0.08
DEFAULT_CANCELLATIONS_RATE_MAX = 0.05
DEFAULT_RETURNS_MIN_SALES = 5
DEFAULT_CANCEL_MIN_N = 5
DEFAULT_CS_OPEN_HOURS = 24.0
DEFAULT_ACCOUNT_DEFECT_RATE_MAX = 0.02
DEFAULT_TRACKING_HOURS_MAX = 48.0
DEFAULT_FULFILLMENT_HOURS_MAX = 72.0
DEFAULT_DUPLICATE_ACTIVE_MAX = 1
TRACKING_ORDER_STATUSES = frozenset({"SIMULATED_ORDER", "AWAITING_SHIP"})


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


def _detail_map(row: Mapping[str, Any]) -> dict[str, Any]:
    raw = row.get("detail_json", row.get("detail"))
    if raw is None:
        return {}
    if isinstance(raw, Mapping):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        if isinstance(parsed, Mapping):
            return dict(parsed)
    return {}


def _flatten_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Merge detail_json keys under top-level (top-level wins when set)."""
    out = dict(row)
    for key, value in _detail_map(row).items():
        if out.get(key) is None:
            out[key] = value
    return out


def _get(row: Mapping[str, Any], key: str, default: Any = None) -> Any:
    if row.get(key) is not None:
        return row.get(key)
    return _detail_map(row).get(key, default)


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _hours_since_order(row: Mapping[str, Any]) -> float | None:
    pre = _f(_get(row, "hours_since_order"))
    if pre is not None:
        return pre
    ordered = _parse_dt(_get(row, "ordered_at"))
    if ordered is None:
        return None
    now = datetime.now(timezone.utc)
    return max(0.0, (now - ordered).total_seconds() / 3600.0)


def _tracking_empty(row: Mapping[str, Any]) -> bool:
    tracking = _get(row, "tracking_number")
    if tracking is None:
        return True
    return str(tracking).strip() == ""


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


def _eval_cost_spike(row: Mapping[str, Any], settings: Settings) -> RuleHit | None:
    last = _f(_get(row, "last_known_cost"))
    curr = _f(_get(row, "dealer_cost"))
    if curr is None:
        curr = _f(_get(row, "net_cost"))
    if last is None or last <= 0 or curr is None:
        return None
    spike = (curr - last) / last
    if spike + 1e-12 >= DEFAULT_COST_SPIKE_PCT:
        pct = spike * 100.0
        return RuleHit(
            RULE_COST_SPIKE,
            SEVERITY_PAUSE,
            f"cost spike {pct:.1f}%",
            {
                "dealer_cost": curr,
                "last_known_cost": last,
                "cost_spike_pct": spike,
                "threshold": DEFAULT_COST_SPIKE_PCT,
            },
        )
    return None


def _eval_returns_rate(row: Mapping[str, Any], settings: Settings) -> RuleHit | None:
    returns = _i(_get(row, "returns"), 0) or 0
    sales = _f(_get(row, "sales_units"), 0.0) or 0.0
    if sales < DEFAULT_RETURNS_MIN_SALES:
        return None
    rate = returns / max(sales, 1.0)
    if rate > DEFAULT_RETURNS_RATE_MAX:
        return RuleHit(
            RULE_RETURNS_RATE_HIGH,
            SEVERITY_PAUSE,
            f"returns rate {rate * 100.0:.1f}%",
            {
                "returns": returns,
                "sales_units": sales,
                "returns_rate": rate,
                "threshold": DEFAULT_RETURNS_RATE_MAX,
            },
        )
    return None


def _eval_cancellation_rate(
    row: Mapping[str, Any], settings: Settings
) -> RuleHit | None:
    cancels = _i(_get(row, "cancellations"), 0) or 0
    sales = _f(_get(row, "sales_units"), 0.0) or 0.0
    n = sales + cancels
    if n < DEFAULT_CANCEL_MIN_N:
        return None
    rate = cancels / max(n, 1.0)
    if rate <= DEFAULT_CANCELLATIONS_RATE_MAX:
        return None
    cancel_fault = _get(row, "cancel_fault")
    severity = SEVERITY_PAUSE
    if cancel_fault is not None and str(cancel_fault).strip().lower() not in {
        "",
        "seller",
    }:
        # Non-seller fault: flag only (seller-fault or unset → pause).
        severity = SEVERITY_FLAG
    return RuleHit(
        RULE_CANCELLATION_RATE_HIGH,
        severity,
        f"cancel rate {rate * 100.0:.1f}%",
        {
            "cancellations": cancels,
            "sales_units": sales,
            "cancellation_rate": rate,
            "threshold": DEFAULT_CANCELLATIONS_RATE_MAX,
            "cancel_fault": cancel_fault,
        },
    )


def _eval_cs_exception_open(
    row: Mapping[str, Any], settings: Settings
) -> RuleHit | None:
    cs_open = _truthy_int(_get(row, "cs_open"))
    hours = _f(_get(row, "cs_open_hours"))
    if hours is None:
        opened = _parse_dt(_get(row, "cs_opened_at"))
        if opened is not None:
            hours = max(
                0.0,
                (datetime.now(timezone.utc) - opened).total_seconds() / 3600.0,
            )
    if cs_open is True and hours is not None and hours >= DEFAULT_CS_OPEN_HOURS:
        return RuleHit(
            RULE_CS_EXCEPTION_OPEN,
            SEVERITY_FLAG,
            "CS case open >=24h",
            {"cs_open": 1, "cs_open_hours": hours, "threshold": DEFAULT_CS_OPEN_HOURS},
        )
    return None


def _eval_account_health(
    row: Mapping[str, Any], settings: Settings
) -> RuleHit | None:
    reasons: list[str] = []
    detail: dict[str, Any] = {}
    defect = _f(_get(row, "account_defect_rate"))
    if defect is not None and defect > DEFAULT_ACCOUNT_DEFECT_RATE_MAX:
        reasons.append(
            f"defect_rate {defect:.4f} > {DEFAULT_ACCOUNT_DEFECT_RATE_MAX}"
        )
        detail["account_defect_rate"] = defect
    if _truthy_int(_get(row, "policy_strike")) is True:
        reasons.append("policy_strike")
        detail["policy_strike"] = 1
    if _truthy_int(_get(row, "selling_limit_hit")) is True:
        reasons.append("selling_limit_hit")
        detail["selling_limit_hit"] = 1
    if not reasons:
        return None
    detail["threshold"] = DEFAULT_ACCOUNT_DEFECT_RATE_MAX
    return RuleHit(
        RULE_ACCOUNT_HEALTH_RISK,
        SEVERITY_FLAG,
        "account health risk",
        detail,
    )


def _eval_tracking_missing(
    row: Mapping[str, Any], settings: Settings
) -> RuleHit | None:
    status = str(_get(row, "order_status") or "").strip().upper()
    if status not in TRACKING_ORDER_STATUSES:
        return None
    hours = _hours_since_order(row)
    if hours is None or hours <= DEFAULT_TRACKING_HOURS_MAX:
        return None
    if not _tracking_empty(row):
        return None
    return RuleHit(
        RULE_TRACKING_MISSING,
        SEVERITY_FLAG,
        f"no tracking after {hours:.1f}h",
        {
            "order_status": status,
            "hours_since_order": hours,
            "tracking_number": None,
            "threshold_hours": DEFAULT_TRACKING_HOURS_MAX,
        },
    )


def _eval_fulfillment_late(
    row: Mapping[str, Any], settings: Settings
) -> RuleHit | None:
    hours = _hours_since_order(row)
    if hours is None or hours <= DEFAULT_FULFILLMENT_HOURS_MAX:
        return None
    ship_status = str(
        _get(row, "ship_status") or _get(row, "shipping_status") or ""
    ).strip().upper()
    if ship_status == "SHIPPED":
        return None
    # Require evidence of an order clock (ordered_at / hours / order_status).
    if (
        _get(row, "ordered_at") is None
        and _get(row, "hours_since_order") is None
        and not str(_get(row, "order_status") or "").strip()
    ):
        return None
    return RuleHit(
        RULE_FULFILLMENT_LATE,
        SEVERITY_FLAG,
        f"fulfillment late {hours:.1f}h",
        {
            "hours_since_order": hours,
            "ship_status": ship_status or None,
            "threshold_hours": DEFAULT_FULFILLMENT_HOURS_MAX,
        },
    )


def _eval_duplicate_listing(
    row: Mapping[str, Any], settings: Settings
) -> RuleHit | None:
    count = _i(_get(row, "active_offer_count"))
    if count is None:
        return None
    if count > DEFAULT_DUPLICATE_ACTIVE_MAX:
        return RuleHit(
            RULE_DUPLICATE_LISTING,
            SEVERITY_PAUSE,
            "duplicate active offers",
            {
                "active_offer_count": count,
                "ebay_item_ids": _get(row, "ebay_item_ids"),
                "threshold": DEFAULT_DUPLICATE_ACTIVE_MAX,
            },
        )
    return None


def _missing_specifics_present(value: Any) -> bool:
    if value is None:
        return False
    flag = _truthy_int(value)
    if flag is True:
        return True
    if flag is False:
        return False
    if isinstance(value, (list, tuple, set)):
        return len(value) > 0
    text = str(value).strip()
    return text not in {"", "[]", "{}", "null", "None"}


def _eval_invalid_listing(
    row: Mapping[str, Any], settings: Settings
) -> RuleHit | None:
    reasons: list[str] = []
    detail: dict[str, Any] = {}
    validation_ok = _truthy_int(_get(row, "listing_validation_ok"))
    if validation_ok is False:
        reasons.append("listing_validation_ok=0")
        detail["listing_validation_ok"] = 0
    missing = _get(row, "missing_specifics")
    if _missing_specifics_present(missing):
        reasons.append("missing_specifics")
        detail["missing_specifics"] = missing
    if _truthy_int(_get(row, "identity_mismatch")) is True:
        reasons.append("identity_mismatch")
        detail["identity_mismatch"] = 1
    if not reasons:
        return None
    return RuleHit(
        RULE_INVALID_LISTING,
        SEVERITY_PAUSE,
        "invalid listing shape",
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
    ExceptionRule(
        RULE_COST_SPIKE,
        "dealer_cost rose >= 10% vs last_known_cost",
        SEVERITY_PAUSE,
        _eval_cost_spike,
    ),
    ExceptionRule(
        RULE_RETURNS_RATE_HIGH,
        "returns/sales > 8% with sales_units >= 5",
        SEVERITY_PAUSE,
        _eval_returns_rate,
    ),
    ExceptionRule(
        RULE_CANCELLATION_RATE_HIGH,
        "cancels/(sales+cancels) > 5% with n >= 5",
        SEVERITY_PAUSE,
        _eval_cancellation_rate,
    ),
    ExceptionRule(
        RULE_CS_EXCEPTION_OPEN,
        "open CS case >= 24h",
        SEVERITY_FLAG,
        _eval_cs_exception_open,
    ),
    ExceptionRule(
        RULE_ACCOUNT_HEALTH_RISK,
        "account defect_rate > 2% / policy_strike / selling_limit_hit",
        SEVERITY_FLAG,
        _eval_account_health,
    ),
    ExceptionRule(
        RULE_TRACKING_MISSING,
        "SIMULATED_ORDER/AWAITING_SHIP > 48h without tracking",
        SEVERITY_FLAG,
        _eval_tracking_missing,
    ),
    ExceptionRule(
        RULE_FULFILLMENT_LATE,
        "order > 72h and not SHIPPED",
        SEVERITY_FLAG,
        _eval_fulfillment_late,
    ),
    ExceptionRule(
        RULE_DUPLICATE_LISTING,
        "active_offer_count > 1",
        SEVERITY_PAUSE,
        _eval_duplicate_listing,
    ),
    ExceptionRule(
        RULE_INVALID_LISTING,
        "listing_validation_ok=0 / missing specifics / identity mismatch",
        SEVERITY_PAUSE,
        _eval_invalid_listing,
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
    flat = _flatten_row(row)
    hits: list[RuleHit] = []
    for rule in active:
        hit = rule.evaluate(flat, settings)
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
    if sku in {GLOBAL_INGEST_SKU, GLOBAL_ACCOUNT_SKU}:
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
            p.order_status AS order_status,
            p.dealer_cost AS dealer_cost,
            p.last_known_cost AS last_known_cost,
            p.net_cost AS net_cost,
            COALESCE(p.returns, c.returns) AS returns,
            COALESCE(p.cancellations, c.cancellations) AS cancellations,
            COALESCE(p.sales_units, c.sales_units) AS sales_units,
            p.tracking_number AS tracking_number,
            p.ordered_at AS ordered_at,
            p.hours_since_order AS hours_since_order,
            p.ship_status AS ship_status,
            p.active_offer_count AS active_offer_count,
            p.ebay_item_ids AS ebay_item_ids,
            p.listing_validation_ok AS listing_validation_ok,
            p.missing_specifics AS missing_specifics,
            p.identity_mismatch AS identity_mismatch,
            p.cs_open AS cs_open,
            p.cs_open_hours AS cs_open_hours,
            p.cs_opened_at AS cs_opened_at,
            p.account_defect_rate AS account_defect_rate,
            p.policy_strike AS policy_strike,
            p.selling_limit_hit AS selling_limit_hit,
            p.cancel_fault AS cancel_fault,
            c.detail_json AS detail_json,
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
            p.order_status AS order_status,
            p.dealer_cost AS dealer_cost,
            p.last_known_cost AS last_known_cost,
            p.net_cost AS net_cost,
            p.returns AS returns,
            p.cancellations AS cancellations,
            p.sales_units AS sales_units,
            p.tracking_number AS tracking_number,
            p.ordered_at AS ordered_at,
            p.hours_since_order AS hours_since_order,
            p.ship_status AS ship_status,
            p.active_offer_count AS active_offer_count,
            p.ebay_item_ids AS ebay_item_ids,
            p.listing_validation_ok AS listing_validation_ok,
            p.missing_specifics AS missing_specifics,
            p.identity_mismatch AS identity_mismatch,
            p.cs_open AS cs_open,
            p.cs_open_hours AS cs_open_hours,
            p.cs_opened_at AS cs_opened_at,
            p.account_defect_rate AS account_defect_rate,
            p.policy_strike AS policy_strike,
            p.selling_limit_hit AS selling_limit_hit,
            p.cancel_fault AS cancel_fault,
            NULL AS detail_json,
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

    # Account-health sentinel row (sku=__ACCOUNT__) when present on products.
    seen = {r["sku"] for r in rows}
    if GLOBAL_ACCOUNT_SKU not in seen:
        acct = conn.execute(
            """
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
                p.order_status AS order_status,
                p.dealer_cost AS dealer_cost,
                p.last_known_cost AS last_known_cost,
                p.net_cost AS net_cost,
                p.returns AS returns,
                p.cancellations AS cancellations,
                p.sales_units AS sales_units,
                p.tracking_number AS tracking_number,
                p.ordered_at AS ordered_at,
                p.hours_since_order AS hours_since_order,
                p.ship_status AS ship_status,
                p.active_offer_count AS active_offer_count,
                p.ebay_item_ids AS ebay_item_ids,
                p.listing_validation_ok AS listing_validation_ok,
                p.missing_specifics AS missing_specifics,
                p.identity_mismatch AS identity_mismatch,
                p.cs_open AS cs_open,
                p.cs_open_hours AS cs_open_hours,
                p.cs_opened_at AS cs_opened_at,
                p.account_defect_rate AS account_defect_rate,
                p.policy_strike AS policy_strike,
                p.selling_limit_hit AS selling_limit_hit,
                p.cancel_fault AS cancel_fault,
                NULL AS detail_json,
                p.pipeline_source AS pipeline_source,
                p.cohort AS cohort,
                NULL AS snapshot_id,
                p.listable_rank AS rank
            FROM products p
            WHERE p.sku = ?
            """,
            (GLOBAL_ACCOUNT_SKU,),
        ).fetchone()
        if acct is not None:
            rows.append(dict(acct))
    return rows



def _cs_open_hours_from_actions(
    conn: sqlite3.Connection, sku: str
) -> float | None:
    """Hours since newest open cs_case/cs_exception action for sku, else None."""
    if not sku:
        return None
    row = conn.execute(
        """
        SELECT ts, decision, detail_json
        FROM actions
        WHERE sku = ? AND action IN ('cs_case', 'cs_exception')
        ORDER BY ts DESC, id DESC
        LIMIT 1
        """,
        (sku,),
    ).fetchone()
    if row is None:
        return None
    decision = str(row["decision"] or "").strip().lower()
    if decision not in {"open", "opened", "pending"}:
        return None
    detail = {}
    raw = row["detail_json"]
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, Mapping):
                detail = dict(parsed)
        except (TypeError, ValueError, json.JSONDecodeError):
            detail = {}
    hours = _f(detail.get("cs_open_hours"))
    if hours is not None:
        return hours
    opened = _parse_dt(detail.get("cs_opened_at") or row["ts"])
    if opened is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - opened).total_seconds() / 3600.0)


def _enrich_row_for_rules(
    conn: sqlite3.Connection, row: Mapping[str, Any]
) -> dict[str, Any]:
    flat = _flatten_row(row)
    if flat.get("cs_open") is None:
        hours = _cs_open_hours_from_actions(conn, str(flat.get("sku") or ""))
        if hours is not None:
            flat["cs_open"] = 1
            flat["cs_open_hours"] = hours
    return flat


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
        hits = evaluate_candidate(_enrich_row_for_rules(conn, row), settings)
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

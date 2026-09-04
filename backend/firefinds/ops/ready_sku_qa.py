"""Automated QA for ready / listable SKUs (gates OFF — never publish/order).

Checks preferred SAFE_NATIONWIDE + DESTINATION_SENSITIVE listable cohort by
default against shipping, MAP/channel, UPC/MPN collision, stock buffer,
contribution floors, SAFE image integrity, and listing draft accuracy.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from firefinds.config import Settings, get_settings
from firefinds.db.schema import init_db
from firefinds.pipelines.authorize import authorize_sku

# Stable rule codes (report / CLI).
RULE_SHIPPING_P75 = "SHIPPING_P75"
RULE_MAP_CHANNEL = "MAP_CHANNEL"
RULE_DUPLICATE_LISTING = "DUPLICATE_LISTING"
RULE_STOCK_BUFFER = "STOCK_BUFFER"
RULE_MARGIN_FLOOR = "MARGIN_FLOOR"
RULE_IMAGE_INTEGRITY = "IMAGE_INTEGRITY"
RULE_LISTING_DRAFT = "LISTING_DRAFT"

PREFERRED_COHORTS = ("SAFE_NATIONWIDE", "DESTINATION_SENSITIVE")
FLAT_SHIP_CAD = 10.0
FLAT_SHIP_EPS = 0.01

RULE_ORDER = (
    RULE_SHIPPING_P75,
    RULE_MAP_CHANNEL,
    RULE_DUPLICATE_LISTING,
    RULE_STOCK_BUFFER,
    RULE_MARGIN_FLOOR,
    RULE_IMAGE_INTEGRITY,
    RULE_LISTING_DRAFT,
)


@dataclass(frozen=True)
class QaFail:
    sku: str
    rule: str
    message: str
    detail: dict[str, Any] = field(default_factory=dict)
    cohort: str | None = None


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


def _parse_image_urls(row: Mapping[str, Any]) -> list[str]:
    urls: list[str] = []
    for key in ("image_urls", "supplier_image_urls"):
        raw = row.get(key)
        if raw is None:
            continue
        if isinstance(raw, str) and raw.strip():
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                if raw.startswith("http"):
                    urls.append(raw.strip())
                continue
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, str) and item.startswith("http"):
                    urls.append(item)
                elif isinstance(item, dict):
                    u = item.get("url") or item.get("Url")
                    if u and str(u).startswith("http"):
                        urls.append(str(u))
    # de-dupe preserve order
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _draft_paths_for_sku(data_dir: Path, sku: str, cohort: str | None) -> list[Path]:
    paths: list[Path] = []
    listing = data_dir / "listing_drafts" / f"{sku}.json"
    if listing.is_file():
        paths.append(listing)
    sub = {
        "SAFE_NATIONWIDE": "safe_nationwide",
        "DESTINATION_SENSITIVE": "destination_sensitive",
    }.get(str(cohort or ""), None)
    if sub:
        p = data_dir / "drafts" / "randmar_first" / sub / f"{sku}.json"
        if p.is_file():
            paths.append(p)
    # Also accept creative ORIGINAL variants under same tree
    if sub:
        for variant in (
            data_dir / "drafts" / "randmar_first" / sub / f"{sku}.ORIGINAL_SUPPLIER.json",
            data_dir / "drafts" / "randmar_first" / sub / f"{sku}_ORIGINAL_SUPPLIER.json",
        ):
            if variant.is_file():
                paths.append(variant)
    return paths


def _validate_draft_payload(draft: Mapping[str, Any], sku: str) -> list[str]:
    problems: list[str] = []
    if draft.get("publish") is True:
        problems.append("publish=true (gates must stay OFF)")
    inv = draft.get("inventory_item")
    if not isinstance(inv, dict):
        problems.append("missing inventory_item")
        return problems
    if str(inv.get("sku") or "") != str(sku):
        problems.append(f"inventory_item.sku mismatch ({inv.get('sku')!r})")
    product = inv.get("product")
    if not isinstance(product, dict):
        problems.append("missing inventory_item.product")
    else:
        title = str(product.get("title") or "").strip()
        if not title:
            problems.append("missing product.title")
    offer = draft.get("offer")
    if not isinstance(offer, dict):
        problems.append("missing offer")
    else:
        price = (
            (offer.get("pricingSummary") or {}).get("price")
            if isinstance(offer.get("pricingSummary"), dict)
            else None
        )
        if not isinstance(price, dict) or not price.get("value"):
            problems.append("missing offer.pricingSummary.price.value")
        qty = offer.get("availableQuantity")
        if qty is None and isinstance(inv.get("availability"), dict):
            qty = (
                (inv.get("availability") or {})
                .get("shipToLocationAvailability", {})
                .get("quantity")
            )
        if qty is None:
            problems.append("missing available quantity")
    return problems


def check_shipping_p75(row: Mapping[str, Any]) -> QaFail | None:
    status = str(row.get("shipping_status") or "").strip().upper()
    p75 = _f(row.get("ship_p75"))
    detail: dict[str, Any] = {
        "shipping_status": status or None,
        "ship_p75": p75,
        "ship_est": _f(row.get("ship_est")),
    }
    problems: list[str] = []
    if status != "RESOLVED":
        problems.append(f"shipping_status={status or 'MISSING'} (want RESOLVED)")
    if p75 is None:
        problems.append("ship_p75 missing")
    elif abs(p75 - FLAT_SHIP_CAD) < FLAT_SHIP_EPS:
        problems.append(f"ship_p75 looks like ${FLAT_SHIP_CAD:g} flat fallback")
    # Flag when only marketing ship_est=10 and no real p75 (already covered) or
    # when ship_model explicitly flat.
    ship_model = str(row.get("ship_model") or "").lower()
    if "flat" in ship_model and p75 is not None and abs(p75 - FLAT_SHIP_CAD) < FLAT_SHIP_EPS:
        problems.append(f"ship_model={row.get('ship_model')!r} with $10 flat")
    if not problems:
        return None
    return QaFail(
        sku=str(row.get("sku")),
        rule=RULE_SHIPPING_P75,
        message="; ".join(problems),
        detail=detail,
        cohort=row.get("cohort"),
    )


def check_map_channel(row: Mapping[str, Any]) -> QaFail | None:
    auth = authorize_sku(row)
    detail = {
        "map_ok": auth["map_ok"],
        "channel_ok": auth["channel_ok"],
        "needs_manual_channel_review": auth["needs_manual_channel_review"],
        "flags": auth["authorization_flags"],
        "sell_price": auth["sell_price"],
        "map": auth["map"],
        "db_map_ok": row.get("map_ok"),
        "db_channel_ok": row.get("channel_ok"),
    }
    problems: list[str] = []
    if not auth["map_ok"]:
        problems.append("MAP authorization failed")
    if not auth["channel_ok"]:
        problems.append("channel authorization failed")
    if row.get("map_ok") == 0:
        problems.append("db map_ok=0")
    if row.get("channel_ok") == 0:
        problems.append("db channel_ok=0")
    # Manual review is a soft flag — count as fail for QA visibility
    if auth["needs_manual_channel_review"]:
        problems.append(
            "needs_manual_channel_review: "
            + (",".join(auth["authorization_flags"]) or "policy")
        )
    if not problems:
        return None
    return QaFail(
        sku=str(row.get("sku")),
        rule=RULE_MAP_CHANNEL,
        message="; ".join(problems),
        detail=detail,
        cohort=row.get("cohort"),
    )


def check_stock_buffer(row: Mapping[str, Any], settings: Settings) -> QaFail | None:
    stock = _i(row.get("stock"), 0) or 0
    buffer = int(settings.stock_buffer)
    if stock > buffer:
        return None
    return QaFail(
        sku=str(row.get("sku")),
        rule=RULE_STOCK_BUFFER,
        message=f"stock {stock} <= buffer {buffer}",
        detail={"stock": stock, "stock_buffer": buffer},
        cohort=row.get("cohort"),
    )


def check_margin_floor(row: Mapping[str, Any], settings: Settings) -> QaFail | None:
    profit = _f(row.get("listable_profit"))
    if profit is None:
        profit = _f(row.get("contribution_profit"))
    margin = _f(row.get("listable_margin"))
    if margin is None:
        margin = _f(row.get("contribution_margin"))
    min_p = float(settings.min_contribution_profit_cad)
    min_m = float(settings.min_contribution_margin)
    problems: list[str] = []
    detail = {
        "profit": profit,
        "margin": margin,
        "min_contribution_profit_cad": min_p,
        "min_contribution_margin": min_m,
    }
    if profit is None:
        problems.append("profit missing")
    elif profit < min_p:
        problems.append(f"profit {profit:.4f} < {min_p}")
    if margin is None:
        problems.append("margin missing")
    elif margin < min_m:
        problems.append(f"margin {margin:.4f} < {min_m}")
    if not problems:
        return None
    return QaFail(
        sku=str(row.get("sku")),
        rule=RULE_MARGIN_FLOOR,
        message="; ".join(problems),
        detail=detail,
        cohort=row.get("cohort"),
    )


def check_image_integrity(row: Mapping[str, Any]) -> QaFail | None:
    """SAFE_NATIONWIDE expects ≥1 authorized supplier/image URL."""
    cohort = str(row.get("cohort") or "")
    if cohort != "SAFE_NATIONWIDE":
        return None
    urls = _parse_image_urls(row)
    count = _i(row.get("image_count"), 0) or 0
    if urls or count >= 1:
        return None
    return QaFail(
        sku=str(row.get("sku")),
        rule=RULE_IMAGE_INTEGRITY,
        message="SAFE_NATIONWIDE missing authorized image URL (image_count=0)",
        detail={"image_count": count, "url_count": len(urls)},
        cohort=cohort,
    )


def check_listing_draft(
    row: Mapping[str, Any], *, data_dir: Path
) -> QaFail | None:
    sku = str(row.get("sku") or "")
    cohort = row.get("cohort")
    paths = _draft_paths_for_sku(data_dir, sku, cohort if isinstance(cohort, str) else None)
    if not paths:
        return QaFail(
            sku=sku,
            rule=RULE_LISTING_DRAFT,
            message="no listing/creative draft file found",
            detail={
                "checked": [
                    str(data_dir / "listing_drafts" / f"{sku}.json"),
                    "data/drafts/randmar_first/{cohort}/",
                ]
            },
            cohort=cohort if isinstance(cohort, str) else None,
        )
    # Validate first readable draft (prefer listing_drafts)
    problems: list[str] = []
    used: str | None = None
    for path in paths:
        try:
            draft = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            problems.append(f"{path.name}: unreadable ({exc})")
            continue
        used = str(path)
        field_problems = _validate_draft_payload(draft, sku)
        if field_problems:
            problems.extend(f"{path.name}: {p}" for p in field_problems)
        else:
            problems = []
            break
    if not problems:
        return None
    return QaFail(
        sku=sku,
        rule=RULE_LISTING_DRAFT,
        message="; ".join(problems) if problems else "draft invalid",
        detail={"draft_path": used, "candidates": [str(p) for p in paths]},
        cohort=cohort if isinstance(cohort, str) else None,
    )


def _collision_index(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    by_upc: dict[str, list[str]] = defaultdict(list)
    by_mpn: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        sku = str(row.get("sku") or "")
        upc = str(row.get("upc_norm") or row.get("upc") or "").strip()
        mpn = str(row.get("mpn_norm") or row.get("mpn") or "").strip().upper()
        mfr = str(row.get("manufacturer") or "").strip().upper()
        if upc:
            by_upc[upc].append(sku)
        if mpn and mfr:
            by_mpn[f"{mfr}::{mpn}"].append(sku)
    return by_upc, by_mpn


def check_duplicate_listing(
    row: Mapping[str, Any],
    *,
    by_upc: Mapping[str, Sequence[str]],
    by_mpn: Mapping[str, Sequence[str]],
) -> QaFail | None:
    sku = str(row.get("sku") or "")
    upc = str(row.get("upc_norm") or row.get("upc") or "").strip()
    mpn = str(row.get("mpn_norm") or row.get("mpn") or "").strip().upper()
    mfr = str(row.get("manufacturer") or "").strip().upper()
    collisions: list[dict[str, Any]] = []
    if upc and upc in by_upc:
        others = [s for s in by_upc[upc] if s != sku]
        if others:
            collisions.append({"key": f"upc:{upc}", "others": others})
    if mpn and mfr:
        key = f"{mfr}::{mpn}"
        others = [s for s in by_mpn.get(key, []) if s != sku]
        if others:
            collisions.append({"key": f"mpn:{key}", "others": others})
    if not collisions:
        return None
    return QaFail(
        sku=sku,
        rule=RULE_DUPLICATE_LISTING,
        message="UPC/MPN collision risk: "
        + "; ".join(f"{c['key']} -> {c['others']}" for c in collisions),
        detail={"collisions": collisions},
        cohort=row.get("cohort") if isinstance(row.get("cohort"), str) else None,
    )


def load_qa_universe(
    conn: sqlite3.Connection,
    *,
    cohorts: Sequence[str] = PREFERRED_COHORTS,
    listable_only: bool = True,
) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in cohorts)
    sql = f"""
        SELECT sku, title, manufacturer, upc, upc_norm, mpn, mpn_norm,
               map, msrp, stock, sell_comp, listable_profit, listable_margin,
               contribution_profit, contribution_margin, shipping_status,
               ship_p75, ship_est, ship_model, ship_quote_n,
               listable_pass, listable, eligible, score_pass, final_profitability,
               cohort, pipeline_source, opportunity_only, map_ok, channel_ok,
               needs_manual_channel_review, image_urls, supplier_image_urls,
               image_count, paused, listable_reason
        FROM products
        WHERE cohort IN ({placeholders})
    """
    params: list[Any] = list(cohorts)
    if listable_only:
        sql += " AND listable_pass = 1"
    sql += " ORDER BY cohort, sku"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def load_collision_catalog(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Broader catalog for collision detection (eligible or listable)."""
    rows = conn.execute(
        """
        SELECT sku, upc, upc_norm, mpn, mpn_norm, manufacturer,
               listable_pass, eligible, cohort
        FROM products
        WHERE (listable_pass = 1 OR eligible = 1 OR score_pass = 1)
        """
    ).fetchall()
    return [dict(r) for r in rows]


def evaluate_sku(
    row: Mapping[str, Any],
    *,
    settings: Settings,
    data_dir: Path,
    by_upc: Mapping[str, Sequence[str]],
    by_mpn: Mapping[str, Sequence[str]],
) -> list[QaFail]:
    fails: list[QaFail] = []
    for fn in (
        lambda: check_shipping_p75(row),
        lambda: check_map_channel(row),
        lambda: check_duplicate_listing(row, by_upc=by_upc, by_mpn=by_mpn),
        lambda: check_stock_buffer(row, settings),
        lambda: check_margin_floor(row, settings),
        lambda: check_image_integrity(row),
        lambda: check_listing_draft(row, data_dir=data_dir),
    ):
        hit = fn()
        if hit is not None:
            fails.append(hit)
    return fails


def _listable_growth_note(
    conn: sqlite3.Connection,
    *,
    snapshot_id: str | None = None,
    prior_preferred: int = 296,
    hourly_checkpoint_listable: int = 311,
) -> dict[str, Any]:
    """Explain preferred SAFE+DEST listable vs prior baselines."""
    total_listable = conn.execute(
        "SELECT COUNT(*) FROM products WHERE listable_pass=1"
    ).fetchone()[0]
    by_cohort = {
        str(r[0] or "NULL"): int(r[1])
        for r in conn.execute(
            """
            SELECT cohort, COUNT(*) FROM products
            WHERE listable_pass=1 GROUP BY cohort
            """
        ).fetchall()
    }
    preferred = sum(by_cohort.get(c, 0) for c in PREFERRED_COHORTS)
    safe_n = by_cohort.get("SAFE_NATIONWIDE", 0)
    dest_n = by_cohort.get("DESTINATION_SENSITIVE", 0)
    ranked_n = conn.execute("SELECT COUNT(*) FROM ranked_queue").fetchone()[0]
    quarantine_bleed = [
        dict(r)
        for r in conn.execute(
            """
            SELECT sku, cohort, pipeline_source, shipping_status, ship_p75,
                   stock, listable_profit, listable_margin
            FROM products
            WHERE listable_pass=1 AND cohort='QUARANTINE_UNRESOLVED'
            ORDER BY sku
            """
        ).fetchall()
    ]
    edf = [
        dict(r)
        for r in conn.execute(
            """
            SELECT sku, cohort, pipeline_source, title
            FROM products
            WHERE listable_pass=1 AND pipeline_source='EBAY_DEMAND_FIRST'
            """
        ).fetchall()
    ]
    snap_bit = f" snapshot={snapshot_id}." if snapshot_id else ""
    if quarantine_bleed:
        q_bit = (
            f"{len(quarantine_bleed)} QUARANTINE_UNRESOLVED still listable_pass "
            f"without SAFE/DEST retag. "
        )
    else:
        q_bit = "No quarantine listable bleed. "
    return {
        "snapshot_id": snapshot_id,
        "prior_preferred_listable": prior_preferred,
        "hourly_checkpoint_total_listable": hourly_checkpoint_listable,
        "current_preferred_listable": preferred,
        "current_total_listable_pass": total_listable,
        "ranked_queue_count": ranked_n,
        "listable_by_cohort": by_cohort,
        "delta_preferred_vs_prior": preferred - prior_preferred,
        "delta_total_vs_prior_preferred": total_listable - prior_preferred,
        "delta_total_vs_hourly_checkpoint": total_listable - hourly_checkpoint_listable,
        "explanation": (
            f"Preferred SAFE+DEST listable is {preferred} "
            f"(SAFE_NATIONWIDE {safe_n} + DESTINATION_SENSITIVE {dest_n})."
            f"{snap_bit} "
            f"Prior preferred baseline was {prior_preferred}; "
            f"hourly checkpoint total listable was {hourly_checkpoint_listable}; "
            f"now total listable_pass={total_listable}, ranked_queue={ranked_n}. "
            + q_bit
            + (
                f"EBAY_DEMAND_FIRST listable: {len(edf)}."
                if edf
                else "No EBAY_DEMAND_FIRST listable."
            )
        ),
        "quarantine_listable_skus": [r["sku"] for r in quarantine_bleed],
        "ebay_demand_first_listable": edf,
    }


def run_ready_sku_qa(
    *,
    settings: Settings | None = None,
    cohorts: Sequence[str] = PREFERRED_COHORTS,
    listable_only: bool = True,
    include_all_listable_note: bool = True,
    top_n: int = 25,
    write_reports: bool = True,
    report_stem: str = "ready_sku_qa_latest",
    snapshot_id: str | None = None,
) -> dict[str, Any]:
    """Run QA across ready SKUs; optionally write JSON + Markdown reports."""
    settings = settings or get_settings()
    data_dir = Path(settings.db_path).parent
    conn = init_db(settings.db_path)

    universe = load_qa_universe(conn, cohorts=cohorts, listable_only=listable_only)
    catalog = load_collision_catalog(conn)
    by_upc, by_mpn = _collision_index(catalog)

    all_fails: list[QaFail] = []
    per_sku: dict[str, list[QaFail]] = {}
    for row in universe:
        fails = evaluate_sku(
            row,
            settings=settings,
            data_dir=data_dir,
            by_upc=by_upc,
            by_mpn=by_mpn,
        )
        if fails:
            per_sku[str(row["sku"])] = fails
            all_fails.extend(fails)

    fail_counts = Counter(f.rule for f in all_fails)
    skus_failing = len(per_sku)
    skus_passing = len(universe) - skus_failing

    # Top failing SKUs by number of rule hits then sku
    top_failing = sorted(
        (
            {
                "sku": sku,
                "fail_count": len(fails),
                "rules": [f.rule for f in fails],
                "messages": [f.message for f in fails],
                "cohort": fails[0].cohort,
            }
            for sku, fails in per_sku.items()
        ),
        key=lambda x: (-x["fail_count"], x["sku"]),
    )[:top_n]

    growth = (
        _listable_growth_note(conn, snapshot_id=snapshot_id)
        if include_all_listable_note
        else None
    )
    gates = {
        "LIVE_LISTINGS_ENABLED": bool(settings.live_listings_enabled),
        "SUPPLIER_ORDERS_ENABLED": bool(settings.supplier_orders_enabled),
        "EBAY_SANDBOX_PUBLISH_ENABLED": bool(settings.ebay_sandbox_publish_enabled),
        "EBAY_PRODUCTION_ENABLED": bool(settings.ebay_production_enabled),
    }

    report: dict[str, Any] = {
        "generated_at": _utc_now(),
        "snapshot_id": snapshot_id,
        "db_path": str(settings.db_path),
        "gates": gates,
        "gates_note": "QA only — never publish/order",
        "cohorts": list(cohorts),
        "listable_only": listable_only,
        "universe_count": len(universe),
        "skus_passing": skus_passing,
        "skus_failing": skus_failing,
        "fail_counts_by_rule": {r: int(fail_counts.get(r, 0)) for r in RULE_ORDER},
        "total_fail_hits": len(all_fails),
        "thresholds": {
            "min_contribution_profit_cad": settings.min_contribution_profit_cad,
            "min_contribution_margin": settings.min_contribution_margin,
            "stock_buffer": settings.stock_buffer,
            "flat_ship_cad_forbidden": FLAT_SHIP_CAD,
        },
        "top_failing_skus": top_failing,
        "fails": [asdict(f) for f in all_fails],
        "listable_growth": growth,
        "universe_by_cohort": dict(
            Counter(str(r.get("cohort") or "") for r in universe)
        ),
    }

    if write_reports:
        reports_dir = data_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        json_path = reports_dir / f"{report_stem}.json"
        md_path = reports_dir / f"{report_stem}.md"
        json_path.write_text(
            json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8"
        )
        md_path.write_text(render_markdown_report(report), encoding="utf-8")
        report["report_json"] = str(json_path)
        report["report_md"] = str(md_path)

    conn.close()
    return report


def render_markdown_report(report: Mapping[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Ready SKU QA")
    lines.append("")
    lines.append(f"Generated: `{report.get('generated_at')}` (UTC)")
    if report.get("snapshot_id"):
        lines.append(f"Snapshot: `{report.get('snapshot_id')}`")
    lines.append("")
    lines.append("## Gates (must stay OFF)")
    for k, v in (report.get("gates") or {}).items():
        lines.append(f"- {k}: **{v}**")
    lines.append("")
    lines.append("## Universe")
    lines.append(
        f"- Cohorts: `{', '.join(report.get('cohorts') or [])}` "
        f"(listable_only={report.get('listable_only')})"
    )
    lines.append(f"- SKUs scanned: **{report.get('universe_count')}**")
    lines.append(
        f"- Passing: **{report.get('skus_passing')}** · "
        f"Failing: **{report.get('skus_failing')}** · "
        f"Total rule hits: **{report.get('total_fail_hits')}**"
    )
    byc = report.get("universe_by_cohort") or {}
    if byc:
        lines.append(
            "- By cohort: "
            + ", ".join(f"{k}={v}" for k, v in sorted(byc.items()))
        )
    lines.append("")
    lines.append("## Fail counts by rule")
    lines.append("")
    lines.append("| Rule | Fails |")
    lines.append("|------|------:|")
    for rule, n in (report.get("fail_counts_by_rule") or {}).items():
        lines.append(f"| `{rule}` | {n} |")
    lines.append("")
    growth = report.get("listable_growth")
    if growth:
        prior = growth.get("prior_preferred_listable")
        cur = growth.get("current_preferred_listable")
        lines.append(f"## Listable growth ({prior} → {cur})")
        lines.append("")
        lines.append(
            f"- Prior preferred (ranked/drafts): "
            f"**{growth.get('prior_preferred_listable')}**"
        )
        lines.append(
            f"- Hourly checkpoint total listable: "
            f"**{growth.get('hourly_checkpoint_total_listable')}**"
        )
        lines.append(
            f"- Current preferred SAFE+DEST listable: "
            f"**{growth.get('current_preferred_listable')}**"
        )
        lines.append(
            f"- Current total `listable_pass`: "
            f"**{growth.get('current_total_listable_pass')}** "
            f"(Δ vs hourly "
            f"{growth.get('delta_total_vs_hourly_checkpoint')})"
        )
        lines.append(
            f"- `ranked_queue` rows: **{growth.get('ranked_queue_count')}**"
        )
        lines.append(f"- Note: {growth.get('explanation')}")
        q = growth.get("quarantine_listable_skus") or []
        if q:
            lines.append(
                f"- Quarantine listable SKUs ({len(q)}): "
                + ", ".join(f"`{s}`" for s in q)
            )
        lines.append("")
    lines.append("## Top failing SKUs")
    lines.append("")
    top = report.get("top_failing_skus") or []
    if not top:
        lines.append("_None — all scanned SKUs passed._")
    else:
        lines.append("| SKU | Cohort | #Rules | Rules |")
        lines.append("|-----|--------|-------:|-------|")
        for row in top:
            rules = ", ".join(f"`{r}`" for r in row.get("rules") or [])
            lines.append(
                f"| `{row.get('sku')}` | {row.get('cohort') or ''} | "
                f"{row.get('fail_count')} | {rules} |"
            )
        lines.append("")
        lines.append("### Messages (top)")
        for row in top[:15]:
            lines.append(f"- `{row.get('sku')}`:")
            for msg in row.get("messages") or []:
                lines.append(f"  - {msg}")
    lines.append("")
    lines.append("## Thresholds")
    th = report.get("thresholds") or {}
    lines.append(
        f"- contribution ≥ `${th.get('min_contribution_profit_cad')}` CAD / "
        f"`{th.get('min_contribution_margin')}` margin"
    )
    lines.append(f"- stock_buffer = `{th.get('stock_buffer')}`")
    lines.append(
        f"- forbid ship_p75 ≈ `${th.get('flat_ship_cad_forbidden')}` flat"
    )
    lines.append("")
    lines.append(
        "_Report is diagnostic only. LIVE_LISTINGS / SUPPLIER_ORDERS stay OFF._\n"
    )
    return "\n".join(lines) + "\n"

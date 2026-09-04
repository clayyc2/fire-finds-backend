"""One-SKU simulated E2E dry-run (never live publish / never supplier Process)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from firefinds.action_log.logger import ActionLogger
from firefinds.config import Settings, get_settings
from firefinds.db.schema import init_db
from firefinds.listings.drafts import build_inventory_draft
from firefinds.pipelines.authorize import authorize_sku
from firefinds.sku_record.constants import (
    CREATIVE_AI_ENHANCED,
    CREATIVE_ORIGINAL_SUPPLIER,
    LISTING_SIMULATED,
    MATCH_A_EXACT,
    ORDER_SIMULATED,
    PIPELINE_RANDMAR_FIRST,
)
from firefinds.sku_record.metrics import get_sku_record, upsert_sku_metrics


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _pick_default_sku(conn, snapshot_id: str = "20260903_1744") -> str | None:
    """Prefer high-rank SAFE_NATIONWIDE with RESOLVED shipping + map_ok."""
    row = conn.execute(
        """
        SELECT c.sku
        FROM candidate_cohorts c
        LEFT JOIN products p ON p.sku = c.sku
        WHERE c.snapshot_id = ?
          AND c.pipeline_source = ?
          AND c.cohort = 'SAFE_NATIONWIDE'
          AND UPPER(IFNULL(c.shipping_status, '')) = 'RESOLVED'
          AND IFNULL(c.fails_expensive_destinations, 0) = 0
        ORDER BY IFNULL(c.rank, 999999) ASC
        LIMIT 1
        """,
        (snapshot_id, PIPELINE_RANDMAR_FIRST),
    ).fetchone()
    if row:
        return str(row["sku"])
    # Fall back to ranked_queue SAFE-like
    row = conn.execute(
        """
        SELECT sku FROM ranked_queue
        WHERE UPPER(IFNULL(shipping_status, '')) = 'RESOLVED'
          AND IFNULL(fails_expensive_destinations, 0) = 0
        ORDER BY rank ASC LIMIT 1
        """
    ).fetchone()
    return str(row["sku"]) if row else None


def recheck_backend_gates(
    product: dict[str, Any],
    *,
    settings: Settings,
) -> dict[str, Any]:
    """Re-check $8/12%, stock buffer, shipping RESOLVED, MAP/channel."""
    checks: dict[str, Any] = {}
    reasons: list[str] = []

    profit = float(product.get("listable_profit") or 0.0)
    margin = float(product.get("listable_margin") or 0.0)
    stock = int(product.get("stock") or 0)
    shipping_status = str(product.get("shipping_status") or "").upper()

    profit_ok = profit >= settings.min_contribution_profit_cad
    checks["profit_ge_8"] = {
        "pass": profit_ok,
        "value": profit,
        "threshold": settings.min_contribution_profit_cad,
    }
    if not profit_ok:
        reasons.append(f"profit_below_{settings.min_contribution_profit_cad}")

    margin_ok = margin >= settings.min_contribution_margin
    checks["margin_ge_12pct"] = {
        "pass": margin_ok,
        "value": margin,
        "threshold": settings.min_contribution_margin,
    }
    if not margin_ok:
        reasons.append(f"margin_below_{settings.min_contribution_margin}")

    stock_ok = stock > settings.stock_buffer
    checks["stock_gt_buffer"] = {
        "pass": stock_ok,
        "value": stock,
        "threshold": settings.stock_buffer,
    }
    if not stock_ok:
        reasons.append(f"stock_leq_buffer_{settings.stock_buffer}")

    ship_ok = shipping_status == "RESOLVED"
    checks["shipping_resolved"] = {
        "pass": ship_ok,
        "value": shipping_status or None,
    }
    if not ship_ok:
        reasons.append("shipping_unresolved")

    auth = authorize_sku(product)
    checks["map_ok"] = {"pass": bool(auth["map_ok"]), "detail": auth}
    checks["channel_ok"] = {
        "pass": bool(auth["channel_ok"]),
        "opportunity_only": auth["opportunity_only"],
    }
    if not auth["map_ok"]:
        reasons.append("map_fail")
    if not auth["channel_ok"]:
        reasons.append("channel_restricted")

    # Live gates must remain OFF for dry-run safety
    gates = {
        "LIVE_LISTINGS_ENABLED": settings.live_listings_enabled,
        "SUPPLIER_ORDERS_ENABLED": settings.supplier_orders_enabled,
        "EBAY_SANDBOX_PUBLISH_ENABLED": settings.ebay_sandbox_publish_enabled,
    }
    checks["feature_gates_off"] = {
        "pass": not any(gates.values()),
        "gates": gates,
    }
    if any(gates.values()):
        reasons.append("live_gate_enabled")

    passed = len(reasons) == 0
    return {
        "pass": passed,
        "reasons": reasons,
        "checks": checks,
        "authorization": auth,
    }


def run_dry_run_sku(
    *,
    sku: str | None = None,
    settings: Settings | None = None,
    snapshot_id: str = "20260903_1744",
    include_ai_twin: bool = True,
    report_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Simulate research → creative → gates → listing → order → ops for one SKU.

    Never calls eBay publish or Randmar Cart/Process. Writes SIMULATED_* statuses
    and a JSON report under data/dry_runs/.
    """
    settings = settings or get_settings()
    data_dir = Path(settings.db_path).parent
    out_dir = Path(report_dir or (data_dir / "dry_runs"))
    out_dir.mkdir(parents=True, exist_ok=True)

    # Safety: refuse if live gates somehow ON
    if (
        settings.live_listings_enabled
        or settings.supplier_orders_enabled
        or settings.ebay_sandbox_publish_enabled
    ):
        raise RuntimeError(
            "dry-run refused: a live gate is ON "
            "(LIVE_LISTINGS_ENABLED / SUPPLIER_ORDERS_ENABLED / "
            "EBAY_SANDBOX_PUBLISH_ENABLED must be false)"
        )

    conn = init_db(settings.db_path)
    logger = ActionLogger(settings.actions_jsonl, conn=conn)
    stages: list[dict[str, Any]] = []
    chosen = sku

    try:
        if not chosen:
            chosen = _pick_default_sku(conn, snapshot_id=snapshot_id)
        if not chosen:
            raise ValueError("no SAFE_NATIONWIDE RESOLVED SKU available for dry-run")

        product_row = conn.execute(
            "SELECT * FROM products WHERE sku=?", (chosen,)
        ).fetchone()
        if product_row is None:
            raise KeyError(f"sku not found: {chosen}")
        product = dict(product_row)

        # Enrich from cohort / ranked_queue when product fields are sparse
        cohort = conn.execute(
            """
            SELECT * FROM candidate_cohorts
            WHERE sku=? AND snapshot_id=? AND pipeline_source=?
            ORDER BY updated_at DESC LIMIT 1
            """,
            (chosen, snapshot_id, PIPELINE_RANDMAR_FIRST),
        ).fetchone()
        ranked = conn.execute(
            "SELECT * FROM ranked_queue WHERE sku=?", (chosen,)
        ).fetchone()
        if cohort:
            for k in (
                "cohort",
                "comparison_cohort_id",
                "pipeline_source",
                "shipping_status",
                "ship_p75",
                "listable_profit",
                "listable_margin",
                "sell_comp",
                "map",
                "rank",
            ):
                if product.get(k) in (None, "") and cohort[k] is not None:
                    product[k] = cohort[k]
        if ranked:
            for k in (
                "shipping_status",
                "ship_p75",
                "listable_profit",
                "listable_margin",
                "sell_comp",
                "rank_score",
            ):
                if product.get(k) in (None, "") and ranked[k] is not None:
                    product[k] = ranked[k]

        comparison_id = product.get("comparison_cohort_id") or (
            f"{snapshot_id}|{PIPELINE_RANDMAR_FIRST}|SAFE_NATIONWIDE"
        )

        # --- Stage 1: Research ---
        demand_refs = {
            "snapshot_id": snapshot_id,
            "cohort": product.get("cohort") or "SAFE_NATIONWIDE",
            "ranked_rank": product.get("rank") or (ranked["rank"] if ranked else None),
            "sources": ["frozen_cohort", "ranked_queue"],
        }
        comp_flags = {
            "provisional_public_ebay": bool(product.get("provisional_public_ebay")),
            "needs_official_ebay_validation": bool(
                product.get("needs_official_ebay_validation", 1)
            ),
            "from_ranked": ranked is not None,
        }
        upsert_sku_metrics(
            chosen,
            {
                "pipeline_source": PIPELINE_RANDMAR_FIRST,
                "match_confidence": MATCH_A_EXACT,
                "demand_evidence_refs": demand_refs,
                "competition_snapshot_flags": comp_flags,
                "comparison_cohort_id": comparison_id,
            },
            settings=settings,
            conn=conn,
            source="dry_run.research",
        )
        logger.log(
            "dry_run_research",
            sku=chosen,
            decision="recorded",
            detail={
                "pipeline_source": PIPELINE_RANDMAR_FIRST,
                "match_confidence": MATCH_A_EXACT,
                "demand_evidence_refs": demand_refs,
            },
            source="dry_run",
        )
        stages.append(
            {
                "stage": "research",
                "status": "ok",
                "pipeline_source": PIPELINE_RANDMAR_FIRST,
                "match_confidence": MATCH_A_EXACT,
            }
        )

        # --- Stage 2: Creative ---
        creative_version = f"cv-{chosen[:8]}-{uuid.uuid4().hex[:8]}"
        draft = build_inventory_draft(
            product,
            stock_buffer=settings.stock_buffer,
            marketplace_id=settings.ebay_marketplace_id,
        )
        draft["pipeline_source"] = PIPELINE_RANDMAR_FIRST
        draft["creative_version_id"] = creative_version
        draft["creative_variant"] = CREATIVE_ORIGINAL_SUPPLIER
        draft["dry_run"] = True
        draft["publish"] = False
        draft_dir = data_dir / "drafts" / "dry_run"
        draft_dir.mkdir(parents=True, exist_ok=True)
        draft_path = draft_dir / f"{chosen}.ORIGINAL_SUPPLIER.json"
        draft_path.write_text(
            json.dumps(draft, indent=2, default=str), encoding="utf-8"
        )
        asset_paths = [str(draft_path)]
        ab_assignment = "A"
        twin_path = None
        if include_ai_twin:
            twin = dict(draft)
            twin["creative_variant"] = CREATIVE_AI_ENHANCED
            twin["creative_version_id"] = f"{creative_version}-ai"
            twin["ab_twin_of"] = creative_version
            twin_path = draft_dir / f"{chosen}.AI_ENHANCED.json"
            twin_path.write_text(
                json.dumps(twin, indent=2, default=str), encoding="utf-8"
            )
            asset_paths.append(str(twin_path))
            ab_assignment = "A|B"

        upsert_sku_metrics(
            chosen,
            {
                "creative_version_id": creative_version,
                "creative_variant": CREATIVE_ORIGINAL_SUPPLIER,
                "asset_paths": asset_paths,
                "ab_assignment": ab_assignment,
                "comparison_cohort_id": comparison_id,
            },
            settings=settings,
            conn=conn,
            source="dry_run.creative",
        )
        logger.log(
            "dry_run_creative",
            sku=chosen,
            decision="drafted",
            detail={
                "creative_version_id": creative_version,
                "creative_variant": CREATIVE_ORIGINAL_SUPPLIER,
                "asset_paths": asset_paths,
                "ab_assignment": ab_assignment,
                "ai_twin": bool(twin_path),
            },
            source="dry_run",
        )
        stages.append(
            {
                "stage": "creative",
                "status": "ok",
                "creative_version_id": creative_version,
                "creative_variant": CREATIVE_ORIGINAL_SUPPLIER,
                "draft_path": str(draft_path),
                "ai_twin_path": str(twin_path) if twin_path else None,
                "ab_assignment": ab_assignment,
            }
        )

        # --- Stage 3: Backend gates ---
        # Refresh product after upserts
        product = dict(
            conn.execute("SELECT * FROM products WHERE sku=?", (chosen,)).fetchone()
        )
        if cohort:
            for k in (
                "listable_profit",
                "listable_margin",
                "sell_comp",
                "map",
                "shipping_status",
                "ship_p75",
            ):
                if product.get(k) in (None, "") and cohort[k] is not None:
                    product[k] = cohort[k]
        if ranked:
            for k in (
                "listable_profit",
                "listable_margin",
                "sell_comp",
                "shipping_status",
                "ship_p75",
            ):
                if product.get(k) in (None, "") and ranked[k] is not None:
                    product[k] = ranked[k]

        gate_result = recheck_backend_gates(product, settings=settings)
        # Persist MAP/channel flags
        conn.execute(
            """
            UPDATE products
            SET map_ok=?, channel_ok=?, needs_manual_channel_review=?,
                updated_at=datetime('now')
            WHERE sku=?
            """,
            (
                1 if gate_result["authorization"]["map_ok"] else 0,
                1 if gate_result["authorization"]["channel_ok"] else 0,
                1
                if gate_result["authorization"]["needs_manual_channel_review"]
                else 0,
                chosen,
            ),
        )
        conn.commit()
        logger.log(
            "dry_run_gates",
            sku=chosen,
            decision="pass" if gate_result["pass"] else "fail",
            detail={
                "reasons": gate_result["reasons"],
                "checks": {
                    k: {"pass": v.get("pass")}
                    for k, v in gate_result["checks"].items()
                },
            },
            source="dry_run",
        )
        stages.append(
            {
                "stage": "backend_gates",
                "status": "pass" if gate_result["pass"] else "fail",
                "result": gate_result,
            }
        )

        listing_status = None
        order_status = None
        tracking = None
        ops: dict[str, Any] = {}

        if gate_result["pass"]:
            # --- Stage 4: Simulated eBay listing (NOT live) ---
            listing_status = LISTING_SIMULATED
            upsert_sku_metrics(
                chosen,
                {"listing_status": listing_status},
                settings=settings,
                conn=conn,
                source="dry_run.listing",
            )
            logger.log(
                "dry_run_listing",
                sku=chosen,
                decision=LISTING_SIMULATED,
                detail={
                    "publish": False,
                    "live_listings_enabled": False,
                    "note": "status only; no eBay Sell publish call",
                },
                source="dry_run",
            )
            stages.append(
                {
                    "stage": "simulated_listing",
                    "status": LISTING_SIMULATED,
                    "publish": False,
                }
            )

            # --- Stage 5: Simulated order (no supplier APIs) ---
            order_status = ORDER_SIMULATED
            upsert_sku_metrics(
                chosen,
                {"order_status": order_status},
                settings=settings,
                conn=conn,
                source="dry_run.order",
            )
            logger.log(
                "dry_run_order",
                sku=chosen,
                decision=ORDER_SIMULATED,
                detail={
                    "supplier_orders_enabled": False,
                    "note": "no Randmar Cart/Process call",
                },
                source="dry_run",
            )
            stages.append(
                {
                    "stage": "simulated_order",
                    "status": ORDER_SIMULATED,
                    "supplier_api_called": False,
                }
            )

            # --- Stage 6: Operations — tracking + pause-on-gate-fail path ---
            tracking = {
                "carrier": "SIMULATED",
                "tracking_number": f"DRY{uuid.uuid4().hex[:12].upper()}",
                "status": "IN_TRANSIT",
                "updated_at": _utc_now(),
            }
            # Exercise pause-on-gate-fail check (gates currently pass → no pause)
            pause_path = {
                "would_pause_on_gate_fail": True,
                "gate_pass": True,
                "paused": False,
                "pause_reason": None,
            }
            logger.log(
                "dry_run_ops",
                sku=chosen,
                decision="tracking_simulated",
                detail={"tracking": tracking, "pause_check": pause_path},
                source="dry_run",
            )
            stages.append(
                {
                    "stage": "operations",
                    "status": "ok",
                    "tracking": tracking,
                    "pause_on_gate_fail": pause_path,
                }
            )
            ops = {"tracking": tracking, "pause_on_gate_fail": pause_path}
        else:
            # Pause-on-gate-fail path when gates fail
            pause_reason = "dry_run_gate_fail:" + ",".join(gate_result["reasons"])
            conn.execute(
                """
                UPDATE products
                SET paused=1, pause_reason=?, updated_at=datetime('now')
                WHERE sku=?
                """,
                (pause_reason, chosen),
            )
            conn.commit()
            logger.log(
                "dry_run_ops",
                sku=chosen,
                decision="paused_on_gate_fail",
                detail={"pause_reason": pause_reason},
                source="dry_run",
            )
            stages.append(
                {
                    "stage": "operations",
                    "status": "paused_on_gate_fail",
                    "pause_reason": pause_reason,
                }
            )
            ops = {"paused": True, "pause_reason": pause_reason}

        record = get_sku_record(chosen, settings=settings, conn=conn)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        report_path = out_dir / f"{chosen}_{stamp}.json"
        report = {
            "sku": chosen,
            "snapshot_id": snapshot_id,
            "generated_at": _utc_now(),
            "dry_run": True,
            "live_publish": False,
            "supplier_order_api_called": False,
            "gates": {
                "LIVE_LISTINGS_ENABLED": settings.live_listings_enabled,
                "SUPPLIER_ORDERS_ENABLED": settings.supplier_orders_enabled,
                "EBAY_SANDBOX_PUBLISH_ENABLED": settings.ebay_sandbox_publish_enabled,
            },
            "stages": stages,
            "backend_gates": gate_result,
            "listing_status": listing_status,
            "order_status": order_status,
            "operations": ops,
            "sku_record_metrics": record.get("metrics"),
            "comparison_cohort_id": comparison_id,
        }
        report_path.write_text(
            json.dumps(report, indent=2, default=str), encoding="utf-8"
        )
        # Also write a stable latest pointer for this SKU
        latest = out_dir / f"{chosen}_latest.json"
        latest.write_text(
            json.dumps(report, indent=2, default=str), encoding="utf-8"
        )
        report["report_path"] = str(report_path)
        report["latest_path"] = str(latest)

        logger.log(
            "dry_run_complete",
            sku=chosen,
            decision="ok" if gate_result["pass"] else "gate_fail",
            detail={"report_path": str(report_path)},
            source="dry_run",
        )
        return report
    finally:
        conn.close()

"""Validate ALL eligible SKUs into a ranked listable queue.

No hard SKU cap. Final listable_pass requires RESOLVED shipping quotes and
MAP-compliant pricing. eBay Browse is optional; missing credentials → provisional
flags, pipeline continues.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from firefinds.action_log.logger import ActionLogger
from firefinds.clients.ebay import (
    CompetitionSnapshot,
    EbayClient,
    EbayCredentialsMissing,
)
from firefinds.config import Settings, get_settings
from firefinds.db.schema import init_db
from firefinds.listings.drafts import build_inventory_draft
from firefinds.scoring.competition import evaluate_listable
from firefinds.scoring.dedupe import dedupe_products
from firefinds.scoring.identifiers import normalize_product_ids
from firefinds.scoring.return_risk import evaluate_return_risk
from firefinds.scoring.shipping import (
    InjectedQuoteProvider,
    RandmarQuoteProvider,
    ShippingQuote,
    ShippingQuoteProvider,
    compute_landed_cost_with_quote,
    pick_fulfillment_warehouse,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _ship_to(settings: Settings) -> dict[str, str]:
    return {
        "Name": settings.ship_to_name,
        "Street1": settings.ship_to_street1,
        "Street2": settings.ship_to_street2,
        "City": settings.ship_to_city,
        "Province": settings.ship_to_province,
        "PostalCode": settings.ship_to_postal_code,
        "Country": settings.ship_to_country,
    }


def load_eligible_products(
    conn,
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Load eligible=1 (synced from score_pass) products."""
    sql = """
        SELECT * FROM products
        WHERE IFNULL(eligible, 0) = 1
           OR (score_pass = 1 AND IFNULL(paused, 0) = 0)
        ORDER BY IFNULL(score, 0) DESC, sku ASC
    """
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    return [dict(r) for r in conn.execute(sql).fetchall()]


def _empty_snapshot(query: str = "", query_type: str = "none") -> CompetitionSnapshot:
    return CompetitionSnapshot(
        query=query,
        query_type=query_type,
        item_count=0,
        lowest_price=None,
        median_price=None,
        sample_url=None,
        raw_total=0,
    )


def _competition_for(
    product: Mapping[str, Any],
    *,
    ebay: EbayClient | None,
    fixture_snap: CompetitionSnapshot | None,
    credentials_ok: bool,
) -> tuple[CompetitionSnapshot, bool, bool]:
    """Return (snapshot, provisional_public_ebay, needs_official_ebay_validation)."""
    if ebay is not None and credentials_ok:
        try:
            snap = ebay.competition_for_product(dict(product))
            return snap, False, False
        except Exception:  # noqa: BLE001
            # Fall through to provisional
            pass
    if fixture_snap is not None:
        return fixture_snap, True, True
    return _empty_snapshot(), True, True


def validate_eligible_queue(
    *,
    settings: Settings | None = None,
    ebay: EbayClient | None = None,
    quote_provider: ShippingQuoteProvider | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    write_drafts: bool = True,
    drafts_dir: Path | None = None,
    fixture_competition: dict[str, CompetitionSnapshot] | None = None,
) -> dict[str, Any]:
    """Run full validation over ALL eligible SKUs; persist ranked_queue.

    Returns summary dict. Does not publish listings. Does not place orders.
    """
    settings = settings or get_settings()
    conn = init_db(settings.db_path)
    logger = ActionLogger(settings.actions_jsonl, conn=conn)

    ebay = ebay or EbayClient(settings)
    credentials_ok = False
    try:
        ebay.require_credentials()
        credentials_ok = True
    except EbayCredentialsMissing:
        credentials_ok = False
        logger.log(
            "ebay_compete",
            decision="credentials_missing_skip_official",
            detail={"note": "using provisional flags; pipeline continues"},
            source="validate-queue",
        )

    if quote_provider is None:
        if settings.ship_quote_enabled:
            try:
                from firefinds.clients.randmar import RandmarClient

                quote_provider = RandmarQuoteProvider(RandmarClient(settings))
            except Exception:  # noqa: BLE001
                quote_provider = InjectedQuoteProvider()
        else:
            quote_provider = InjectedQuoteProvider()

    ship_to = _ship_to(settings)
    rows = load_eligible_products(conn, limit=limit)
    logger.log(
        "validate_queue",
        decision="start",
        detail={"eligible_loaded": len(rows), "limit": limit, "dry_run": dry_run},
        source="validate-queue",
    )

    # Normalize IDs
    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        ids = normalize_product_ids(row.get("upc"), row.get("mpn"))
        row = dict(row)
        row["upc_norm"] = ids.upc_norm
        row["upc_valid"] = 1 if ids.upc_valid else 0
        row["mpn_norm"] = ids.mpn_norm
        normalized_rows.append(row)
        logger.log(
            "normalize_ids",
            sku=row.get("sku"),
            decision="ok" if ids.upc_valid or ids.mpn_norm else "weak_ids",
            detail={
                "upc_norm": ids.upc_norm,
                "upc_valid": ids.upc_valid,
                "mpn_norm": ids.mpn_norm,
            },
            source="validate-queue",
        )

    # Dedupe
    deduped, merges = dedupe_products(normalized_rows)
    for m in merges:
        logger.log(
            "dedupe",
            sku=m.dropped_sku,
            decision="dropped",
            detail={
                "kept_sku": m.kept_sku,
                "key": m.key,
                "reason": m.reason,
            },
            source="validate-queue",
        )
    kept_skus = {str(r.get("sku")) for r in deduped}

    results: list[dict[str, Any]] = []
    for row in deduped:
        sku = str(row.get("sku") or "")
        # Return risk
        risk = evaluate_return_risk(
            row,
            heavy_weight_lb=settings.return_risk_heavy_weight_lb,
            high_msrp_cad=settings.return_risk_high_msrp_cad,
        )
        if risk.excluded:
            logger.log(
                "return_risk",
                sku=sku,
                decision="exclude",
                detail={"reasons": list(risk.reasons), "risk": risk.risk_score},
                source="validate-queue",
            )
            row_out = {
                **row,
                "listable_pass": 0,
                "listable_reason": ";".join(risk.reasons),
                "return_risk_score": risk.risk_score,
                "rank_score": 0.0,
                "shipping_status": "UNRESOLVED",
                "final_profitability": 0,
                "dedupe_kept": 1,
            }
            results.append(row_out)
            continue

        # Shipping quote (required for final)
        try:
            quote: ShippingQuote = quote_provider.quote_product(row, ship_to=ship_to)
        except Exception as exc:  # noqa: BLE001
            quote = ShippingQuote.unresolved(
                reason=f"provider_error:{type(exc).__name__}",
                warehouse=pick_fulfillment_warehouse(row),
            )
        landed, quote = compute_landed_cost_with_quote(row, quote)
        logger.log(
            "shipping_quote",
            sku=sku,
            decision=quote.status,
            detail={
                "cost_cad": quote.cost_cad,
                "source": quote.source,
                "warehouse": quote.warehouse,
                "carrier": quote.carrier,
                "reason": (quote.detail or {}).get("reason"),
            },
            source="validate-queue",
        )

        # Competition (official or provisional)
        fix = (fixture_competition or {}).get(sku)
        snap, provisional, needs_official = _competition_for(
            row,
            ebay=ebay,
            fixture_snap=fix,
            credentials_ok=credentials_ok,
        )

        product_for_eval = dict(row)
        if landed is not None:
            product_for_eval["landed_cost"] = landed
            product_for_eval["landed_includes_shipping"] = True
        product_for_eval["net_cost"] = float(
            row.get("net_cost") or row.get("dealer_cost") or 0
        ) - float(row.get("rebate") or 0)

        margin = evaluate_listable(
            product_for_eval,
            snap,
            settings,
            provisional_public_ebay=provisional,
            needs_official_ebay_validation=needs_official or (not credentials_ok),
            return_risk=risk.risk_score,
            shipping_status=quote.status,
            shipping_cost_cad=quote.cost_cad,
        )
        logger.log(
            "listable_eval",
            sku=sku,
            decision="pass" if margin.listable_pass else "reject",
            detail={
                "reasons": list(margin.reasons),
                "sell_comp": margin.sell_comp,
                "profit": margin.contribution_profit,
                "margin": margin.contribution_margin,
                "rank_score": margin.rank_score,
                "shipping_status": margin.shipping_status,
                "final_profitability": margin.final_profitability,
                "provisional_public_ebay": margin.provisional_public_ebay,
                "needs_official_ebay_validation": margin.needs_official_ebay_validation,
            },
            source="validate-queue",
        )

        row_out = {
            **row,
            "ship_est": quote.cost_cad,
            "ship_warehouse": quote.warehouse,
            "ship_model": quote.source,
            "shipping_status": quote.status,
            "landed_cost": landed if landed is not None else row.get("landed_cost"),
            "ebay_comp_lowest": snap.lowest_price,
            "ebay_comp_median": snap.median_price,
            "ebay_comp_count": snap.item_count,
            "ebay_comp_url": snap.sample_url,
            "ebay_comp_query": snap.query,
            "ebay_comp_query_type": snap.query_type,
            "ebay_comp_at": _utc_now(),
            "sell_comp": margin.sell_comp,
            "listable_pass": 1 if margin.listable_pass else 0,
            "listable": 1 if margin.listable_pass else 0,
            "listable_reason": margin.reason,
            "listable_profit": margin.contribution_profit,
            "listable_margin": margin.contribution_margin,
            "sales_probability": margin.sales_probability,
            "expected_monthly_units": margin.expected_monthly_units,
            "expected_monthly_contribution_profit": (
                margin.expected_monthly_contribution_profit
            ),
            "rank_score": margin.rank_score,
            "provisional_public_ebay": 1 if margin.provisional_public_ebay else 0,
            "needs_official_ebay_validation": (
                1 if margin.needs_official_ebay_validation else 0
            ),
            "return_risk_score": risk.risk_score,
            "final_profitability": 1 if margin.final_profitability else 0,
            "dedupe_kept": 1,
            "opportunity_only": 1 if row.get("opportunity_only") else 0,
        }
        results.append(row_out)

    # Mark dropped dupes
    for row in normalized_rows:
        sku = str(row.get("sku") or "")
        if sku not in kept_skus:
            results.append(
                {
                    **row,
                    "listable_pass": 0,
                    "listable_reason": "deduped_variant",
                    "rank_score": 0.0,
                    "dedupe_kept": 0,
                    "shipping_status": "UNRESOLVED",
                    "final_profitability": 0,
                }
            )

    # Rank survivors (final_profitability / listable_pass) — NO hard cap
    survivors = [
        r
        for r in results
        if int(r.get("listable_pass") or 0) == 1
        and int(r.get("dedupe_kept") or 0) == 1
    ]
    survivors.sort(
        key=lambda r: (
            -float(r.get("rank_score") or 0),
            -float(r.get("expected_monthly_contribution_profit") or 0),
            str(r.get("sku") or ""),
        )
    )
    for i, r in enumerate(survivors, start=1):
        r["listable_rank"] = i

    summary = {
        "eligible_loaded": len(rows),
        "after_dedupe": len(deduped),
        "dedupe_merges": len(merges),
        "listable_pass_count": len(survivors),
        "shipping_resolved": sum(
            1 for r in results if r.get("shipping_status") == "RESOLVED"
        ),
        "shipping_unresolved": sum(
            1 for r in results if r.get("shipping_status") != "RESOLVED"
        ),
        "ebay_credentials_present": credentials_ok,
        "dry_run": dry_run,
        "top_skus": [r.get("sku") for r in survivors[:25]],
    }

    if dry_run:
        logger.log(
            "validate_queue",
            decision="dry_run_complete",
            detail=summary,
            source="validate-queue",
        )
        logger.close()
        return {"summary": summary, "survivors": survivors, "results": results}

    # Persist product columns + ranked_queue + ebay_competition
    product_cols = [
        "upc_norm",
        "upc_valid",
        "mpn_norm",
        "ship_est",
        "ship_warehouse",
        "ship_model",
        "landed_cost",
        "ebay_comp_lowest",
        "ebay_comp_median",
        "ebay_comp_count",
        "ebay_comp_url",
        "ebay_comp_query",
        "ebay_comp_query_type",
        "ebay_comp_at",
        "sell_comp",
        "listable",
        "listable_pass",
        "listable_rank",
        "listable_reason",
        "listable_profit",
        "listable_margin",
        "sales_probability",
        "expected_monthly_units",
        "expected_monthly_contribution_profit",
        "rank_score",
        "provisional_public_ebay",
        "needs_official_ebay_validation",
        "return_risk_score",
        "dedupe_kept",
        "opportunity_only",
        "title",
        "category",
        "product_type",
        "unit_weight",
        "qty_montreal",
        "qty_toronto",
        "qty_vancouver",
        "qty_laval",
        "qty_edmonton",
        "net_cost",
    ]
    # Ensure shipping_status column via migrate (may need add)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(products)").fetchall()}
    for name, decl in (
        ("shipping_status", "TEXT"),
        ("final_profitability", "INTEGER DEFAULT 0"),
    ):
        if name not in cols:
            conn.execute(f"ALTER TABLE products ADD COLUMN {name} {decl}")
            product_cols.append(name)
    if "shipping_status" in cols:
        product_cols.append("shipping_status")
    if "final_profitability" in cols or True:
        if "final_profitability" not in product_cols:
            product_cols.append("final_profitability")

    for r in results:
        sets = []
        vals: list[Any] = []
        for c in product_cols:
            if c in r:
                sets.append(f"{c}=?")
                vals.append(r.get(c))
        sets.append("updated_at=datetime('now')")
        vals.append(r.get("sku"))
        if sets:
            conn.execute(
                f"UPDATE products SET {', '.join(sets)} WHERE sku=?",
                vals,
            )
        # ebay_competition history
        conn.execute(
            """
            INSERT INTO ebay_competition (
                sku, queried_at, query, query_type, item_count,
                lowest_price, median_price, sample_url, sell_comp,
                contribution_profit, contribution_margin, listable_pass,
                reason, provisional_public_ebay, needs_official_ebay_validation
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                r.get("sku"),
                r.get("ebay_comp_at") or _utc_now(),
                r.get("ebay_comp_query"),
                r.get("ebay_comp_query_type"),
                r.get("ebay_comp_count") or 0,
                r.get("ebay_comp_lowest"),
                r.get("ebay_comp_median"),
                r.get("ebay_comp_url"),
                r.get("sell_comp"),
                r.get("listable_profit"),
                r.get("listable_margin"),
                int(r.get("listable_pass") or 0),
                r.get("listable_reason"),
                int(r.get("provisional_public_ebay") or 0),
                int(r.get("needs_official_ebay_validation") or 1),
            ),
        )

    conn.execute("DELETE FROM ranked_queue")
    for r in survivors:
        conn.execute(
            """
            INSERT INTO ranked_queue (
                rank, sku, rank_score, expected_monthly_contribution_profit,
                sales_probability, sell_comp, listable_profit, listable_margin,
                map, stock, provisional_public_ebay,
                needs_official_ebay_validation, reason, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                r.get("listable_rank"),
                r.get("sku"),
                r.get("rank_score"),
                r.get("expected_monthly_contribution_profit"),
                r.get("sales_probability"),
                r.get("sell_comp"),
                r.get("listable_profit"),
                r.get("listable_margin"),
                r.get("map"),
                r.get("stock"),
                int(r.get("provisional_public_ebay") or 0),
                int(r.get("needs_official_ebay_validation") or 1),
                r.get("listable_reason"),
            ),
        )
    conn.commit()

    if write_drafts:
        out_dir = Path(drafts_dir or (settings.db_path.parent / "listing_drafts"))
        out_dir.mkdir(parents=True, exist_ok=True)
        for r in survivors:
            draft = build_inventory_draft(
                r,
                stock_buffer=settings.stock_buffer,
                marketplace_id=settings.ebay_marketplace_id,
            )
            (out_dir / f"{r['sku']}.json").write_text(
                json.dumps(draft, indent=2), encoding="utf-8"
            )

    # Export JSON of full ranked queue
    export_path = settings.db_path.parent / "ranked_queue.json"
    export_path.write_text(
        json.dumps(
            {
                "summary": summary,
                "queue": [
                    {
                        "rank": r.get("listable_rank"),
                        "sku": r.get("sku"),
                        "rank_score": r.get("rank_score"),
                        "expected_monthly_contribution_profit": r.get(
                            "expected_monthly_contribution_profit"
                        ),
                        "sales_probability": r.get("sales_probability"),
                        "sell_comp": r.get("sell_comp"),
                        "map": r.get("map"),
                        "shipping_status": r.get("shipping_status"),
                        "ship_est": r.get("ship_est"),
                        "listable_profit": r.get("listable_profit"),
                        "listable_margin": r.get("listable_margin"),
                        "provisional_public_ebay": bool(
                            r.get("provisional_public_ebay")
                        ),
                        "needs_official_ebay_validation": bool(
                            r.get("needs_official_ebay_validation")
                        ),
                    }
                    for r in survivors
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    logger.log(
        "validate_queue",
        decision="complete",
        detail=summary,
        source="validate-queue",
    )
    logger.close()
    summary["export_path"] = str(export_path)
    return {"summary": summary, "survivors": survivors, "results": results}


def export_listable_json(
    *,
    settings: Settings | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Export ranked_queue rows (optional soft display limit only)."""
    settings = settings or get_settings()
    conn = init_db(settings.db_path)
    soft = limit
    if soft is None and settings.listable_export_limit > 0:
        soft = settings.listable_export_limit
    sql = "SELECT * FROM ranked_queue ORDER BY rank ASC"
    params: tuple[Any, ...] = ()
    if soft and soft > 0:
        sql += " LIMIT ?"
        params = (int(soft),)
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def health_check(*, settings: Settings | None = None) -> dict[str, Any]:
    """DB / gates / secrets-presence (not values) / last ingest health."""
    settings = settings or get_settings()
    conn = init_db(settings.db_path)
    product_count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    eligible = conn.execute(
        "SELECT COUNT(*) FROM products WHERE IFNULL(eligible,0)=1 OR score_pass=1"
    ).fetchone()[0]
    listable = conn.execute(
        "SELECT COUNT(*) FROM products WHERE IFNULL(listable_pass,0)=1"
    ).fetchone()[0]
    queue_n = conn.execute("SELECT COUNT(*) FROM ranked_queue").fetchone()[0]
    last_ingest = conn.execute(
        "SELECT ts, action, decision FROM actions WHERE action IN ('ingest','ingest-live') "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()
    ebay = EbayClient(settings)
    from firefinds.clients.randmar import RandmarClient

    randmar = RandmarClient(settings)
    return {
        "ok": True,
        "db_path": str(settings.db_path),
        "product_count": product_count,
        "eligible_count": eligible,
        "listable_pass_count": listable,
        "ranked_queue_count": queue_n,
        "gates": {
            "LIVE_LISTINGS_ENABLED": settings.live_listings_enabled,
            "SUPPLIER_ORDERS_ENABLED": settings.supplier_orders_enabled,
            "EBAY_PRODUCTION_ENABLED": settings.ebay_production_enabled,
            "EBAY_SANDBOX_PUBLISH_ENABLED": settings.ebay_sandbox_publish_enabled,
        },
        "secrets_present": {
            "randmar_credentials": randmar.credentials_present(),
            "ebay_credentials": ebay.credentials_present(),
        },
        "last_ingest": dict(last_ingest) if last_ingest else None,
        "shipping_policy": (
            "Final listable requires RESOLVED Randmar shipping quote; "
            "no marketing flat-rate default."
        ),
    }

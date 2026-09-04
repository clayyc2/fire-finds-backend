#!/usr/bin/env python3
"""Lexmark micro-EDF Estimate-only multi-city shipping quotes.

SKUs from Plankton UnitWeight report:
  734646709910 / 55B1000 — UnitWeight ~2.15
  734646709927 / 55B1H00 — UnitWeight ~3.0

Estimate / ShippingLabel only (never Cart Process, never $10 flat, never publish).
Gates stay OFF. Same Band-A / Canon PG-245 enrichment + p75 + re-score pattern.
"""
from __future__ import annotations

import json
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from firefinds.config import get_settings
from firefinds.db.schema import init_db
from firefinds.pipelines.authorize import authorize_sku
from firefinds.scoring.competition import evaluate_listable
from firefinds.scoring.shipping import (
    REPRESENTATIVE_DESTINATIONS,
    RandmarQuoteProvider,
    flag_expensive_destinations,
    pick_fulfillment_warehouse,
    quote_representative_destinations,
)
from firefinds.services_quote import persist_destination_quotes
from firefinds.clients.ebay import CompetitionSnapshot
from firefinds.clients.randmar import RandmarClient

SKUS = ["734646709910", "734646709927"]
PRODUCTS_ALL = Path("/workspace/firefinds/data/products_all.json")
UNITWEIGHT_REPORT = Path(
    "/workspace/firefinds/data/reports/lexmark_unitweight_for_estimate_20260904.json"
)
MT = ZoneInfo("America/Edmonton")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _local_stamp() -> str:
    return datetime.now(MT).strftime("%Y%m%d_%H%M")


def _empty_snap() -> CompetitionSnapshot:
    return CompetitionSnapshot(
        query="",
        query_type="none",
        item_count=0,
        lowest_price=None,
        median_price=None,
        sample_url=None,
        raw_total=0,
    )


def _load_catalog() -> dict[str, dict[str, Any]]:
    rows = json.loads(PRODUCTS_ALL.read_text(encoding="utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        sku = str(r.get("RandmarSKU") or "").strip()
        if sku:
            out[sku] = r
    return out


def _enrich(
    product: dict[str, Any],
    cat: dict[str, Any] | None,
    *,
    source_label: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    p = dict(product)
    enrich_meta: dict[str, Any] = {
        "source": source_label if cat else None,
        "unit_weight_before": product.get("unit_weight"),
        "unit_weight_after": product.get("unit_weight"),
        "enriched_weight": False,
        "enriched_qtys": False,
    }
    if not cat:
        return p, enrich_meta
    uw = cat.get("UnitWeight")
    if uw is not None and (p.get("unit_weight") is None or float(p.get("unit_weight") or 0) <= 0):
        try:
            p["unit_weight"] = float(uw)
            enrich_meta["enriched_weight"] = True
        except (TypeError, ValueError):
            pass
    wh_map = {
        "QuantityLaval": "qty_laval",
        "QuantityMontreal": "qty_montreal",
        "QuantityToronto": "qty_toronto",
        "QuantityVancouver": "qty_vancouver",
        "QuantityEdmonton": "qty_edmonton",
    }
    for src, dst in wh_map.items():
        q = cat.get(src)
        if q is None:
            continue
        try:
            qi = int(q)
        except (TypeError, ValueError):
            continue
        prev = int(p.get(dst) or 0)
        p[dst] = qi
        p[src] = qi
        name = src.replace("Quantity", "")
        p[f"Quantity{name}"] = qi
        if prev != qi:
            enrich_meta["enriched_qtys"] = True
    for k in ("UnitLength", "UnitWidth", "UnitHeight"):
        if cat.get(k) is not None and p.get(k) is None:
            p[k] = cat.get(k)
    if cat.get("RandmarTitle") and not p.get("title"):
        p["title"] = cat.get("RandmarTitle")
    if cat.get("ManufacturerName") and not p.get("manufacturer"):
        p["manufacturer"] = cat.get("ManufacturerName")
    if cat.get("MPN") and not p.get("mpn"):
        p["mpn"] = cat.get("MPN")
    if cat.get("UPC") and not p.get("upc"):
        p["upc"] = cat.get("UPC")
    if cat.get("MAP") is not None and (p.get("map") is None or float(p.get("map") or 0) <= 0):
        try:
            p["map"] = float(cat["MAP"])
        except (TypeError, ValueError):
            pass
    enrich_meta["unit_weight_after"] = p.get("unit_weight")
    return p, enrich_meta


def _wh_qty(product: dict[str, Any]) -> dict[str, int]:
    return {
        "montreal": int(product.get("qty_montreal") or product.get("QuantityMontreal") or 0),
        "toronto": int(product.get("qty_toronto") or product.get("QuantityToronto") or 0),
        "vancouver": int(product.get("qty_vancouver") or product.get("QuantityVancouver") or 0),
        "laval": int(product.get("qty_laval") or product.get("QuantityLaval") or 0),
        "edmonton": int(product.get("qty_edmonton") or product.get("QuantityEdmonton") or 0),
    }


def _econ_slice(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "map": row.get("map"),
        "dealer_cost": row.get("dealer_cost"),
        "net_cost": row.get("net_cost"),
        "rebate": row.get("rebate"),
        "sell_comp": row.get("sell_comp"),
        "contribution_profit": row.get("contribution_profit") or row.get("listable_profit"),
        "contribution_margin": row.get("contribution_margin") or row.get("listable_margin"),
        "listable_pass": row.get("listable_pass"),
        "listable_profit": row.get("listable_profit"),
        "listable_margin": row.get("listable_margin"),
        "final_profitability": row.get("final_profitability"),
        "ship_p75": row.get("ship_p75"),
        "ship_est": row.get("ship_est"),
        "shipping_status": row.get("shipping_status"),
    }


def main() -> int:
    settings = get_settings()
    assert not settings.live_listings_enabled, "LIVE_LISTINGS must be OFF"
    assert not settings.supplier_orders_enabled, "SUPPLIER_ORDERS must be OFF"

    stamp = _local_stamp()
    out_json = Path(
        f"/workspace/firefinds/data/reports/lexmark_estimate_quotes_{stamp}.json"
    )
    out_md = Path(
        f"/workspace/firefinds/data/reports/lexmark_estimate_quotes_{stamp}.md"
    )

    uw_report = {}
    if UNITWEIGHT_REPORT.exists():
        uw_report = json.loads(UNITWEIGHT_REPORT.read_text(encoding="utf-8"))

    catalog = _load_catalog()
    conn = init_db(settings.db_path)
    client = RandmarClient(settings)
    if not client.credentials_present():
        print("RANDMAR_AUTH_FULLY_BLOCKED: credentials missing")
        return 2
    try:
        client.fetch_token()
    except Exception as exc:  # noqa: BLE001
        print(f"RANDMAR_AUTH_FULLY_BLOCKED: {type(exc).__name__}: {exc}")
        return 2

    # Estimate-only — Cart failed before for Band-A; never Process.
    provider = RandmarQuoteProvider(
        client, prefer=("shipping_label_estimate",)
    )
    sleep = float(settings.ship_quote_sleep_sec or 0.35)

    results: list[dict[str, Any]] = []
    completed: list[str] = []
    p75_samples: dict[str, float] = {}
    newly_listable: list[str] = []
    skipped_missing_weight: list[str] = []

    for sku in SKUS:
        print(f"=== quoting {sku} (Estimate-only) ===", flush=True)
        row = conn.execute("SELECT * FROM products WHERE sku=?", (sku,)).fetchone()
        if row is None:
            results.append(
                {
                    "sku": sku,
                    "resolution": "UNRESOLVED",
                    "error": "missing_from_products_db",
                    "quoted": False,
                    "finally_listable": False,
                    "fail_reasons": ["missing_from_products_db"],
                }
            )
            continue
        before = dict(row)
        listable_before = bool(int(before.get("listable_pass") or 0))
        final_before = bool(int(before.get("final_profitability") or 0)) and listable_before

        cat = catalog.get(sku)
        uw_note = (uw_report.get("skus") or {}).get(sku) or {}
        source_label = "products_all.json"
        product, enrich_meta = _enrich(before, cat, source_label=source_label)
        enrich_meta["unitweight_report"] = {
            "UnitWeight": uw_note.get("UnitWeight"),
            "mpn": uw_note.get("mpn"),
            "MAP": uw_note.get("MAP"),
        }

        # Skip Estimate if UnitWeight still missing after enrich
        uw = product.get("unit_weight")
        if uw is None or float(uw or 0) <= 0:
            skipped_missing_weight.append(sku)
            results.append(
                {
                    "sku": sku,
                    "mpn": before.get("mpn") or (cat or {}).get("MPN"),
                    "resolution": "UNRESOLVED",
                    "error": "missing_unit_weight",
                    "quoted": False,
                    "finally_listable": False,
                    "fail_reasons": ["missing_unit_weight_skip_estimate"],
                    "enrichment": enrich_meta,
                    "economics_before": _econ_slice(before),
                    "unit_weight": uw,
                }
            )
            print(f"  SKIP missing UnitWeight", flush=True)
            completed.append(sku)
            continue

        dealer = float(product.get("dealer_cost") or 0.0)
        rebate = float(product.get("rebate") or 0.0)
        net = float(product.get("net_cost") or 0.0)
        if net <= 0:
            net = max(0.0, dealer - rebate)
            product["net_cost"] = net

        try:
            bundle = quote_representative_destinations(
                provider, product, sleep_sec=sleep
            )
            persist_destination_quotes(conn, sku, bundle)
            conn.commit()
        except Exception as exc:  # noqa: BLE001
            tb = traceback.format_exc()
            print(f"QUOTE_FAIL {sku}: {exc}\n{tb}", flush=True)
            msg = f"{type(exc).__name__}: {exc}"
            results.append(
                {
                    "sku": sku,
                    "resolution": "UNRESOLVED",
                    "quoted": False,
                    "error": msg,
                    "finally_listable": False,
                    "fail_reasons": [msg],
                    "enrichment": enrich_meta,
                    "economics_before": _econ_slice(before),
                    "unit_weight": product.get("unit_weight"),
                }
            )
            completed.append(sku)
            continue

        product_for_eval = dict(product)
        product_for_eval["net_cost"] = net
        margin = evaluate_listable(
            product_for_eval,
            _empty_snap(),
            settings,
            provisional_public_ebay=True,
            needs_official_ebay_validation=True,
            return_risk=0.0,
            shipping_status=bundle.status,
            shipping_cost_cad=bundle.p75_cad,
        )
        auth = authorize_sku(
            {
                **product_for_eval,
                "sell_comp": margin.sell_comp
                or product.get("sell_comp")
                or product.get("map"),
            }
        )
        flag = flag_expensive_destinations(
            bundle.dest_costs,
            sell_price=float(margin.sell_comp or 0.0),
            net_cost=float(net),
            rebate=rebate,
            min_profit_cad=settings.min_contribution_profit_cad,
            min_margin=settings.min_contribution_margin,
            ebay_fee_rate=settings.ebay_fee_rate,
            ebay_fee_fixed=settings.ebay_fee_fixed,
        )

        conn.execute(
            """
            UPDATE products SET
              sell_comp=?,
              listable_pass=?,
              listable=?,
              listable_reason=?,
              listable_profit=?,
              listable_margin=?,
              contribution_profit=?,
              contribution_margin=?,
              final_profitability=?,
              fails_expensive_destinations=?,
              unit_weight=COALESCE(unit_weight, ?),
              qty_laval=CASE WHEN IFNULL(qty_laval,0)=0 THEN ? ELSE qty_laval END,
              qty_montreal=CASE WHEN IFNULL(qty_montreal,0)=0 THEN ? ELSE qty_montreal END,
              qty_toronto=CASE WHEN IFNULL(qty_toronto,0)=0 THEN ? ELSE qty_toronto END,
              qty_vancouver=CASE WHEN IFNULL(qty_vancouver,0)=0 THEN ? ELSE qty_vancouver END,
              qty_edmonton=CASE WHEN IFNULL(qty_edmonton,0)=0 THEN ? ELSE qty_edmonton END,
              net_cost=COALESCE(NULLIF(net_cost,0), ?),
              title=COALESCE(title, ?),
              manufacturer=COALESCE(manufacturer, ?),
              updated_at=datetime('now')
            WHERE sku=?
            """,
            (
                margin.sell_comp,
                1 if margin.listable_pass else 0,
                1 if margin.listable_pass else 0,
                ";".join(margin.reasons) if margin.reasons else None,
                margin.contribution_profit,
                margin.contribution_margin,
                margin.contribution_profit,
                margin.contribution_margin,
                1 if margin.final_profitability else 0,
                1 if flag.fails_expensive_destinations else 0,
                product.get("unit_weight"),
                int(product.get("qty_laval") or 0),
                int(product.get("qty_montreal") or 0),
                int(product.get("qty_toronto") or 0),
                int(product.get("qty_vancouver") or 0),
                int(product.get("qty_edmonton") or 0),
                net,
                product.get("title"),
                product.get("manufacturer"),
                sku,
            ),
        )
        conn.commit()

        after_db = dict(
            conn.execute("SELECT * FROM products WHERE sku=?", (sku,)).fetchone()
        )

        finally_listable = bool(margin.final_profitability and margin.listable_pass)
        if finally_listable and not final_before:
            newly_listable.append(sku)

        dest_quotes = []
        for dq in bundle.quotes:
            q = dq.quote
            dest_quotes.append(
                {
                    "dest_id": dq.destination.dest_id,
                    "city": dq.destination.city,
                    "province": dq.destination.province,
                    "postal_code": dq.destination.postal_code,
                    "status": q.status,
                    "cost_cad": q.cost_cad,
                    "source": q.source,
                    "carrier": q.carrier,
                    "method_id": q.method_id,
                    "method_label": q.method_label,
                    "warehouse": q.warehouse or pick_fulfillment_warehouse(product),
                    "detail_reason": (q.detail or {}).get("reason"),
                }
            )

        quote_sources = sorted(
            {dq.quote.source for dq in bundle.quotes if dq.quote.source}
        )
        if bundle.p75_cad is not None:
            p75_samples[sku] = round(float(bundle.p75_cad), 2)

        resolution = (
            "RESOLVED" if bundle.status == "RESOLVED" else "UNRESOLVED"
        )
        fail_reasons = list(margin.reasons) if margin.reasons else []
        if resolution == "UNRESOLVED":
            fail_reasons.append(f"shipping_{bundle.status}")
        if not finally_listable and not fail_reasons:
            fail_reasons.append("not_finally_listable")

        results.append(
            {
                "sku": sku,
                "mpn": before.get("mpn") or (cat or {}).get("MPN") or uw_note.get("mpn"),
                "manufacturer": before.get("manufacturer")
                or (cat or {}).get("ManufacturerName")
                or "Lexmark",
                "title": product.get("title")
                or (cat or {}).get("RandmarTitle")
                or uw_note.get("Title"),
                "stock": before.get("stock"),
                "unit_weight": product.get("unit_weight"),
                "warehouse_qty": _wh_qty(product),
                "fulfillment_warehouse": pick_fulfillment_warehouse(product),
                "enrichment": enrich_meta,
                "shipping_status_before": before.get("shipping_status"),
                "economics_before": _econ_slice(before),
                "provisional_public_ebay": True,
                "needs_official_ebay_validation": True,
                "quoted": True,
                "method": "shipping_label_estimate",
                "quote_sources": quote_sources,
                "resolution": resolution,
                "shipping_status_after": bundle.status,
                "p75_cad": bundle.p75_cad,
                "resolved_n": bundle.resolved_n,
                "unresolved_n": bundle.unresolved_n,
                "dest_costs": bundle.dest_costs,
                "dest_quotes": dest_quotes,
                "economics_after_eval": {
                    "sell_comp_eval": margin.sell_comp,
                    "sell_comp_source": "map_floor_no_competition_snapshot",
                    "fees": margin.fees,
                    "contribution_profit": margin.contribution_profit,
                    "contribution_margin": margin.contribution_margin,
                    "listable_pass": margin.listable_pass,
                    "final_profitability": margin.final_profitability,
                    "reasons": list(margin.reasons),
                    "shipping_status": margin.shipping_status,
                    "shipping_cost_cad": margin.shipping_cost_cad,
                },
                "authorization": auth,
                "expensive_dest_flag": flag.as_dict(),
                "finally_listable": finally_listable,
                "fail_reasons": fail_reasons,
                "economics_after_db": _econ_slice(after_db),
                "destinations": [d.city for d in REPRESENTATIVE_DESTINATIONS],
            }
        )
        completed.append(sku)
        print(
            f"  -> {resolution} p75={bundle.p75_cad} "
            f"listable={finally_listable} reasons={fail_reasons} "
            f"wt={product.get('unit_weight')}",
            flush=True,
        )

    resolved_skus = sum(1 for r in results if r.get("resolution") == "RESOLVED")
    unresolved_skus = sum(1 for r in results if r.get("resolution") != "RESOLVED")
    listable_n = sum(1 for r in results if r.get("finally_listable"))

    payload = {
        "meta": {
            "generated_at": _utc_now(),
            "generated_at_mt": datetime.now(MT).replace(microsecond=0).isoformat(),
            "stamp": stamp,
            "skus_requested": SKUS,
            "skus_completed": completed,
            "stay_dark": True,
            "mode": "Estimate-only multi-dest p75 (ShippingLabel/Estimate); never Process; never $10 flat",
            "prefer": ["shipping_label_estimate"],
            "unitweight_report": str(UNITWEIGHT_REPORT),
            "enrichment": "products_all.json UnitWeight + Quantity* warehouses",
            "gates": {
                "LIVE_LISTINGS_ENABLED": bool(settings.live_listings_enabled),
                "SUPPLIER_ORDERS_ENABLED": bool(settings.supplier_orders_enabled),
                "flipped": False,
            },
            "destinations": [d.city for d in REPRESENTATIVE_DESTINATIONS],
            "never_process": True,
            "never_flat_10": True,
            "never_publish_orders": True,
            "did_not_expand_final5_or_wave25": True,
        },
        "counts": {
            "requested": len(SKUS),
            "completed": len(completed),
            "resolved": resolved_skus,
            "unresolved": unresolved_skus,
            "finally_listable": listable_n,
            "newly_listable": len(newly_listable),
            "skipped_missing_weight": len(skipped_missing_weight),
        },
        "newly_listable": newly_listable,
        "skipped_missing_weight": skipped_missing_weight,
        "p75_samples": p75_samples,
        "results": results,
    }
    out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        f"# Lexmark Estimate quotes `{stamp}`",
        "",
        f"Generated: `{payload['meta']['generated_at']}` UTC / `{payload['meta']['generated_at_mt']}` MT",
        "",
        "- Mode: **ShippingLabel/Estimate only** (never Cart Process, never $10 flat)",
        "- Gates OFF; publish/orders OFF",
        "- Destinations: Calgary, Vancouver, Toronto, Montreal, Halifax (p75)",
        f"- Enrichment: `products_all.json` UnitWeight + warehouse qtys",
        f"- UnitWeight report: `{UNITWEIGHT_REPORT.name}`",
        "",
        "## Counts",
        "",
        f"- requested: {payload['counts']['requested']}",
        f"- resolved: {payload['counts']['resolved']}",
        f"- unresolved: {payload['counts']['unresolved']}",
        f"- finally_listable: {payload['counts']['finally_listable']}",
        f"- newly_listable: {payload['counts']['newly_listable']}",
        "",
        "## SKU outcomes",
        "",
        "| SKU | MPN | Wt | Resolution | p75 CAD | Dest costs | finally_listable | Fail reasons |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        dest_s = (
            ", ".join(f"{k}={v}" for k, v in (r.get("dest_costs") or {}).items())
            if r.get("dest_costs")
            else "—"
        )
        fails = "; ".join(r.get("fail_reasons") or []) or "—"
        lines.append(
            f"| {r.get('sku')} | {r.get('mpn')} | {r.get('unit_weight')} | "
            f"{r.get('resolution')} | {r.get('p75_cad')} | {dest_s} | "
            f"{'yes' if r.get('finally_listable') else 'no'} | {fails} |"
        )
    lines.append("")
    if listable_n == 0:
        lines.append(
            "**0 listable** — ship may resolve but economics still fail gates."
        )
        lines.append("")
    for r in results:
        lines.append(f"### {r.get('sku')}")
        lines.append("")
        lines.append(
            f"- resolution: **{r.get('resolution')}** · p75={r.get('p75_cad')} · "
            f"finally_listable={'yes' if r.get('finally_listable') else 'no'}"
        )
        lines.append(
            f"- weight={r.get('unit_weight')} · warehouse={r.get('fulfillment_warehouse')} · "
            f"qty={r.get('warehouse_qty')}"
        )
        ea = r.get("economics_after_eval") or {}
        lines.append(
            f"- sell_comp={ea.get('sell_comp_eval')} profit={ea.get('contribution_profit')} "
            f"margin={ea.get('contribution_margin')} fees={ea.get('fees')}"
        )
        lines.append(f"- fail_reasons: {r.get('fail_reasons')}")
        if r.get("dest_quotes"):
            lines.append("- per-dest:")
            for dq in r["dest_quotes"]:
                lines.append(
                    f"  - {dq.get('city')}: status={dq.get('status')} "
                    f"cost={dq.get('cost_cad')} source={dq.get('source')} "
                    f"carrier={dq.get('carrier')}"
                )
        lines.append("")

    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"WROTE {out_json}", flush=True)
    print(f"WROTE {out_md}", flush=True)
    print(
        f"SUMMARY resolved={resolved_skus} unresolved={unresolved_skus} "
        f"listable={listable_n}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

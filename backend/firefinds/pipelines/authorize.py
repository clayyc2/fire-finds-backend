"""MAP / eBay-channel authorization and draft Inventory payloads (never publish)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from firefinds.config import Settings, get_settings
from firefinds.db.schema import init_db
from firefinds.listings.drafts import build_inventory_draft
from firefinds.pipelines.tags import (
    PIPELINE_RANDMAR_FIRST,
    ab_metric_placeholders,
)
from firefinds.scoring.competition import apply_map_floor


def authorize_sku(product: Mapping[str, Any]) -> dict[str, Any]:
    """Enforce MAP floor and flag channel / MAP policy issues.

    Returns authorization fields:
      map_ok, channel_ok, needs_manual_channel_review, flags, sell_price
    """
    map_price = float(product.get("map") or 0.0)
    raw_sell = float(product.get("sell_comp") or 0.0)
    sell, below_map_attempt = apply_map_floor(raw_sell, map_price)
    # If sell still somehow under MAP, fail hard
    map_ok = True
    flags: list[str] = []
    if map_price > 0 and sell + 1e-9 < map_price:
        map_ok = False
        flags.append("sell_below_map")
        sell = map_price
    if below_map_attempt:
        flags.append("market_under_map_floored")

    opportunity_only = bool(product.get("opportunity_only"))
    # Buyability and opportunity status never establish eBay resale permission.
    evidence = product.get("channel_evidence")
    channel_ok = (product.get("channel_allowed") is True and
                  isinstance(evidence, str) and bool(evidence.strip()) and not opportunity_only)
    if opportunity_only:
        flags.append("opportunity_only_channel_restricted")

    # Manual review when MAP policy is awkward or channel metadata is incomplete
    needs_manual = not channel_ok
    if not channel_ok:
        flags.append("ebay_channel_permission_unresolved")
    if opportunity_only:
        needs_manual = True
    if below_map_attempt and map_price > 0:
        needs_manual = True
        flags.append("map_policy_review")
    # Missing MAP with competition sell present — review before live
    if map_price <= 0 and sell > 0:
        flags.append("missing_map")
        needs_manual = True

    return {
        "map_ok": map_ok,
        "channel_ok": channel_ok,
        "needs_manual_channel_review": needs_manual,
        "authorization_flags": flags,
        "sell_price": sell,
        "map": map_price,
        "opportunity_only": opportunity_only,
    }


def authorize_and_draft_survivors(
    *,
    settings: Settings | None = None,
    snapshot_id: str,
    cohorts: list[str] | None = None,
    drafts_dir: Path | None = None,
    pipeline_source: str = PIPELINE_RANDMAR_FIRST,
) -> dict[str, Any]:
    """Authorize SAFE + DESTINATION_SENSITIVE SKUs and write draft payloads.

    Never publishes. Drafts land under cohort-separated dirs by default:
      data/drafts/randmar_first/safe_nationwide/
      data/drafts/randmar_first/destination_sensitive/
    """
    settings = settings or get_settings()
    data_dir = Path(settings.db_path).parent
    out_dir = Path(
        drafts_dir or (data_dir / "drafts" / "randmar_first")
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    _COHORT_SUB = {
        "SAFE_NATIONWIDE": "safe_nationwide",
        "DESTINATION_SENSITIVE": "destination_sensitive",
    }

    want = set(
        cohorts
        or ("SAFE_NATIONWIDE", "DESTINATION_SENSITIVE")
    )
    conn = init_db(settings.db_path)
    # Prefer cohort table; fall back to ranked_queue split
    rows = conn.execute(
        """
        SELECT c.*, p.title, p.manufacturer, p.mpn, p.mpn_norm, p.upc, p.upc_norm,
               p.stock, p.unit_weight, p.opportunity_only, p.category, p.product_type,
               p.dealer_cost, p.rebate, p.net_cost
        FROM candidate_cohorts c
        LEFT JOIN products p ON p.sku = c.sku
        WHERE c.pipeline_source = ? AND c.snapshot_id = ?
          AND c.cohort IN ({placeholders})
        ORDER BY IFNULL(c.rank, 999999), c.sku
        """.format(
            placeholders=",".join("?" for _ in want)
        ),
        (pipeline_source, snapshot_id, *sorted(want)),
    ).fetchall()
    products = [dict(r) for r in rows]

    drafts_written = 0
    authorized: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for product in products:
        auth = authorize_sku(product)
        product_for_draft = dict(product)
        product_for_draft["sell_comp"] = auth["sell_price"]
        draft = build_inventory_draft(
            product_for_draft,
            stock_buffer=settings.stock_buffer,
            marketplace_id=settings.ebay_marketplace_id,
        )
        draft["pipeline_source"] = pipeline_source
        draft["cohort"] = product.get("cohort")
        draft["comparison_cohort_id"] = product.get("comparison_cohort_id")
        draft["snapshot_id"] = snapshot_id
        draft["authorization"] = {
            "map_ok": auth["map_ok"],
            "channel_ok": auth["channel_ok"],
            "needs_manual_channel_review": auth["needs_manual_channel_review"],
            "flags": auth["authorization_flags"],
        }
        draft.update(ab_metric_placeholders())

        record = {
            "sku": product.get("sku"),
            "cohort": product.get("cohort"),
            "pipeline_source": pipeline_source,
            "comparison_cohort_id": product.get("comparison_cohort_id"),
            **auth,
            **ab_metric_placeholders(),
        }

        # Survivors still get drafts even if channel_ok is false — flagged for review.
        # Hard skip only when map_ok is False after floor (should be rare).
        if not auth["map_ok"]:
            record["draft_path"] = None
            skipped.append(record)
            continue

        cohort_name = str(product.get("cohort") or "SAFE_NATIONWIDE")
        sub = _COHORT_SUB.get(cohort_name, cohort_name.lower())
        cohort_dir = out_dir / sub
        cohort_dir.mkdir(parents=True, exist_ok=True)
        path = cohort_dir / f"{product['sku']}.json"
        path.write_text(json.dumps(draft, indent=2, default=str), encoding="utf-8")
        record["draft_path"] = str(path)
        record["draft_cohort_dir"] = str(cohort_dir)
        authorized.append(record)
        drafts_written += 1

        # Persist auth flags onto candidate_cohorts detail
        detail = {
            **(json.loads(product["detail_json"]) if product.get("detail_json") else {}),
            "authorization": auth,
        }
        conn.execute(
            """
            UPDATE candidate_cohorts
            SET detail_json=?, updated_at=datetime('now')
            WHERE sku=? AND pipeline_source=? AND snapshot_id=?
            """,
            (
                json.dumps(detail, default=str),
                product.get("sku"),
                pipeline_source,
                snapshot_id,
            ),
        )

    conn.commit()
    by_cohort: dict[str, int] = {}
    for r in authorized:
        c = str(r.get("cohort") or "")
        by_cohort[c] = by_cohort.get(c, 0) + 1
    summary = {
        "snapshot_id": snapshot_id,
        "pipeline_source": pipeline_source,
        "cohorts": sorted(want),
        "candidates": len(products),
        "drafts_written": drafts_written,
        "drafts_by_cohort": by_cohort,
        "skipped_map_fail": len(skipped),
        "needs_manual_channel_review": sum(
            1 for r in authorized if r.get("needs_manual_channel_review")
        ),
        "channel_ok_false": sum(1 for r in authorized if not r.get("channel_ok")),
        "drafts_dir": str(out_dir),
        "safe_nationwide_dir": str(out_dir / "safe_nationwide"),
        "destination_sensitive_dir": str(out_dir / "destination_sensitive"),
    }
    (out_dir / "_authorization_summary.json").write_text(
        json.dumps(
            {"summary": summary, "authorized": authorized, "skipped": skipped},
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    conn.close()
    return {"summary": summary, "authorized": authorized, "skipped": skipped}

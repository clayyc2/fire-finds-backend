"""Batch-write optimized draft fields + creative A/B metadata (never publish).

Listing & Creative writes ORIGINAL_SUPPLIER / AI_ENHANCED variants into:
  data/drafts/randmar_first/safe_nationwide/
  data/drafts/randmar_first/destination_sensitive/
and upserts creative_* fields onto the shared SKU record.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Mapping

from firefinds.config import Settings, get_settings
from firefinds.db.schema import init_db
from firefinds.listings.drafts import build_inventory_draft
from firefinds.pipelines.tags import (
    COHORT_DESTINATION_SENSITIVE,
    COHORT_SAFE_NATIONWIDE,
    PIPELINE_RANDMAR_FIRST,
    ab_metric_placeholders,
)
from firefinds.sku_record.constants import (
    CREATIVE_AI_ENHANCED,
    CREATIVE_ORIGINAL_SUPPLIER,
)
from firefinds.sku_record.metrics import upsert_sku_metrics

_COHORT_DIR = {
    COHORT_SAFE_NATIONWIDE: "safe_nationwide",
    COHORT_DESTINATION_SENSITIVE: "destination_sensitive",
}


def cohort_draft_subdir(cohort: str) -> str:
    """Map cohort enum → drafts subdirectory name."""
    return _COHORT_DIR.get(cohort, cohort.lower())


def optimize_draft_fields(
    product: Mapping[str, Any],
    *,
    creative_variant: str,
    stock_buffer: int = 2,
    marketplace_id: str = "EBAY_CA",
) -> dict[str, Any]:
    """Build Inventory-shaped draft with optimized title/description fields.

    ORIGINAL_SUPPLIER keeps catalog copy (normalized).
    AI_ENHANCED applies deterministic copy improvements (no external AI call).
    Never sets publish=true.
    """
    brand = str(product.get("manufacturer") or "").strip()
    mpn = str(product.get("mpn_norm") or product.get("mpn") or "").strip()
    upc = str(product.get("upc_norm") or product.get("upc") or "").strip()
    raw_title = str(product.get("title") or "").strip()
    category = str(product.get("category") or product.get("product_type") or "").strip()

    if creative_variant == CREATIVE_AI_ENHANCED:
        # Deterministic "AI-enhanced" stub: clearer Brand + MPN title + bullet desc
        parts = [p for p in (brand, mpn) if p]
        title = " ".join(parts) if parts else (raw_title or mpn or str(product.get("sku")))
        if category and category.lower() not in title.lower():
            title = f"{title} — {category}"[:80]
        else:
            title = title[:80]
        bullets = [
            f"Brand: {brand}" if brand else None,
            f"MPN: {mpn}" if mpn else None,
            f"UPC: {upc}" if upc else None,
            f"Condition: New",
            "Ships from authorized Canadian distributor inventory.",
        ]
        description = "<br/>".join(f"• {b}" for b in bullets if b)
        if raw_title and raw_title not in description:
            description = f"{raw_title}<br/><br/>{description}"
    else:
        # ORIGINAL_SUPPLIER — catalog as-is, lightly normalized
        title = (raw_title or f"{brand} {mpn}".strip() or str(product.get("sku")))[:80]
        description = raw_title or title

    product_for_draft = dict(product)
    product_for_draft["title"] = title
    draft = build_inventory_draft(
        product_for_draft,
        stock_buffer=stock_buffer,
        marketplace_id=marketplace_id,
    )
    # Override description fields with optimized copy
    draft["inventory_item"]["product"]["title"] = title[:80]
    draft["inventory_item"]["product"]["description"] = description
    draft["offer"]["listingDescription"] = description
    draft["creative_variant"] = creative_variant
    draft["publish"] = False
    draft["draft"] = True
    draft["live_listings_enabled"] = False
    draft["ebay_sandbox_publish_enabled"] = False
    draft.update(ab_metric_placeholders())
    return draft


def batch_write_creative_drafts(
    *,
    settings: Settings | None = None,
    snapshot_id: str,
    cohorts: list[str] | None = None,
    pipeline_source: str = PIPELINE_RANDMAR_FIRST,
    include_ai_twin: bool = True,
    limit: int | None = None,
    drafts_root: Path | None = None,
) -> dict[str, Any]:
    """Batch-write creative drafts into cohort-separated dirs + SKU metrics.

    Writes under data/drafts/randmar_first/{safe_nationwide,destination_sensitive}/
    as ``{sku}.ORIGINAL_SUPPLIER.json`` (+ optional ``.AI_ENHANCED.json``).
    Updates shared SKU creative_version_id / creative_variant / asset_paths.
    Never publishes.
    """
    from firefinds.pipelines.authorize import authorize_sku

    settings = settings or get_settings()
    data_dir = Path(settings.db_path).parent
    root = Path(
        drafts_root
        or (data_dir / "drafts" / ("randmar_first" if pipeline_source == PIPELINE_RANDMAR_FIRST else pipeline_source.lower()))
    )
    want = list(
        cohorts
        or (COHORT_SAFE_NATIONWIDE, COHORT_DESTINATION_SENSITIVE)
    )
    # Priority: SAFE_NATIONWIDE first
    order = {
        COHORT_SAFE_NATIONWIDE: 0,
        COHORT_DESTINATION_SENSITIVE: 1,
    }
    want_sorted = sorted(want, key=lambda c: order.get(c, 99))

    conn = init_db(settings.db_path)
    rows = conn.execute(
        """
        SELECT c.*, p.title, p.manufacturer, p.mpn, p.mpn_norm, p.upc, p.upc_norm,
               p.stock, p.unit_weight, p.opportunity_only, p.category, p.product_type,
               p.dealer_cost, p.rebate, p.net_cost, p.sell_comp AS product_sell_comp
        FROM candidate_cohorts c
        LEFT JOIN products p ON p.sku = c.sku
        WHERE c.pipeline_source = ? AND c.snapshot_id = ?
          AND c.cohort IN ({placeholders})
        ORDER BY
          CASE c.cohort
            WHEN 'SAFE_NATIONWIDE' THEN 0
            WHEN 'DESTINATION_SENSITIVE' THEN 1
            ELSE 2
          END,
          IFNULL(c.rank, 999999), c.sku
        """.format(placeholders=",".join("?" for _ in want_sorted)),
        (pipeline_source, snapshot_id, *want_sorted),
    ).fetchall()
    products = [dict(r) for r in rows]
    if limit is not None:
        products = products[: int(limit)]

    written: list[dict[str, Any]] = []
    by_cohort: dict[str, int] = {c: 0 for c in want_sorted}

    for product in products:
        sku = str(product.get("sku") or "")
        if not sku:
            continue
        cohort = str(product.get("cohort") or COHORT_SAFE_NATIONWIDE)
        sub = cohort_draft_subdir(cohort)
        out_dir = root / sub
        out_dir.mkdir(parents=True, exist_ok=True)

        auth = authorize_sku(product)
        if not auth["map_ok"]:
            continue
        product_for_draft = dict(product)
        product_for_draft["sell_comp"] = auth["sell_price"]
        if product_for_draft.get("sell_comp") in (None, 0, 0.0):
            product_for_draft["sell_comp"] = product.get("product_sell_comp") or product.get("map")

        creative_version = f"cv-{sku[:8]}-{uuid.uuid4().hex[:8]}"
        comparison_id = product.get("comparison_cohort_id") or (
            f"{snapshot_id}|{pipeline_source}|{cohort}"
        )

        original = optimize_draft_fields(
            product_for_draft,
            creative_variant=CREATIVE_ORIGINAL_SUPPLIER,
            stock_buffer=settings.stock_buffer,
            marketplace_id=settings.ebay_marketplace_id,
        )
        original["pipeline_source"] = pipeline_source
        original["cohort"] = cohort
        original["comparison_cohort_id"] = comparison_id
        original["snapshot_id"] = snapshot_id
        original["creative_version_id"] = creative_version
        original["authorization"] = {
            "map_ok": auth["map_ok"],
            "channel_ok": auth["channel_ok"],
            "needs_manual_channel_review": auth["needs_manual_channel_review"],
            "flags": auth["authorization_flags"],
        }

        orig_path = out_dir / f"{sku}.ORIGINAL_SUPPLIER.json"
        orig_path.write_text(
            json.dumps(original, indent=2, default=str), encoding="utf-8"
        )
        asset_paths = [str(orig_path)]
        ab_assignment = "A"
        ai_path = None

        if include_ai_twin:
            twin = optimize_draft_fields(
                product_for_draft,
                creative_variant=CREATIVE_AI_ENHANCED,
                stock_buffer=settings.stock_buffer,
                marketplace_id=settings.ebay_marketplace_id,
            )
            twin["pipeline_source"] = pipeline_source
            twin["cohort"] = cohort
            twin["comparison_cohort_id"] = comparison_id
            twin["snapshot_id"] = snapshot_id
            twin["creative_version_id"] = f"{creative_version}-ai"
            twin["ab_twin_of"] = creative_version
            twin["authorization"] = original["authorization"]
            ai_path = out_dir / f"{sku}.AI_ENHANCED.json"
            ai_path.write_text(
                json.dumps(twin, indent=2, default=str), encoding="utf-8"
            )
            asset_paths.append(str(ai_path))
            ab_assignment = "A|B"

        upsert_sku_metrics(
            sku,
            {
                "pipeline_source": pipeline_source,
                "creative_version_id": creative_version,
                "creative_variant": CREATIVE_ORIGINAL_SUPPLIER,
                "asset_paths": asset_paths,
                "ab_assignment": ab_assignment,
                "comparison_cohort_id": comparison_id,
            },
            settings=settings,
            conn=conn,
            source="listings.creative_batch",
        )

        record = {
            "sku": sku,
            "cohort": cohort,
            "creative_version_id": creative_version,
            "original_path": str(orig_path),
            "ai_enhanced_path": str(ai_path) if ai_path else None,
            "ab_assignment": ab_assignment,
        }
        written.append(record)
        by_cohort[cohort] = by_cohort.get(cohort, 0) + 1

    conn.commit()
    summary = {
        "snapshot_id": snapshot_id,
        "pipeline_source": pipeline_source,
        "cohorts": want_sorted,
        "skus_written": len(written),
        "by_cohort": by_cohort,
        "include_ai_twin": include_ai_twin,
        "drafts_root": str(root),
        "publish": False,
        "safe_nationwide_dir": str(root / "safe_nationwide"),
        "destination_sensitive_dir": str(root / "destination_sensitive"),
    }
    summary_path = root / "_creative_batch_summary.json"
    root.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps({"summary": summary, "written": written}, indent=2, default=str),
        encoding="utf-8",
    )
    conn.close()
    return {"summary": summary, "written": written}

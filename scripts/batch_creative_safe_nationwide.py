#!/usr/bin/env python3
"""Batch Listing & Creative for SAFE_NATIONWIDE RANDMAR_FIRST SKUs.

- Moves DESTINATION_SENSITIVE flat drafts aside (held tag)
- Writes ORIGINAL_SUPPLIER + AI_ENHANCED twins under safe_nationwide/
- Refreshes flat {sku}.json with creative_variants (publish=false)
- Blocks AI image twins (no authorized supplier imagery)
- Upserts shared SKU creative metrics
- Writes creative_reports JSON

Never enables live publish.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from firefinds.config import get_settings  # noqa: E402
from firefinds.db.schema import init_db  # noqa: E402
from firefinds.listings.drafts import build_inventory_draft  # noqa: E402
from firefinds.pipelines.authorize import authorize_sku  # noqa: E402
from firefinds.pipelines.tags import (  # noqa: E402
    COHORT_DESTINATION_SENSITIVE,
    COHORT_SAFE_NATIONWIDE,
    PIPELINE_RANDMAR_FIRST,
    ab_metric_placeholders,
)
from firefinds.scoring.identifiers import (  # noqa: E402
    canonicalize_mpn,
    normalize_upc,
)
from firefinds.sku_record.constants import (  # noqa: E402
    CREATIVE_AI_ENHANCED,
    CREATIVE_ORIGINAL_SUPPLIER,
)
from firefinds.sku_record.metrics import upsert_sku_metrics  # noqa: E402

SNAPSHOT_ID = "20260903_1744"
COMPARISON_ID = f"{SNAPSHOT_ID}|{PIPELINE_RANDMAR_FIRST}|{COHORT_SAFE_NATIONWIDE}"
IMAGE_BLOCK_STATUS = "BLOCKED_NO_AUTHORIZED_SUPPLIER_IMAGERY"
DEST_HELD_TAG = "DESTINATION_SENSITIVE_HELD"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _trunc80(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if len(text) <= 80:
        return text
    cut = text[:80]
    # Prefer word boundary
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" -–,;:")[:80]


def load_catalog(path: Path) -> tuple[dict[str, dict], dict[tuple[str, str], dict]]:
    with path.open(encoding="utf-8") as f:
        catalog = json.load(f)
    by_upc: dict[str, dict] = {}
    by_mpn_mfr: dict[tuple[str, str], dict] = {}
    for item in catalog:
        u, _ = normalize_upc(item.get("UPC"))
        if u and u not in by_upc:
            by_upc[u] = item
        mpn = canonicalize_mpn(item.get("MPN"))
        mfr = (item.get("ManufacturerName") or "").strip().upper()
        if mpn and mfr and (mpn, mfr) not in by_mpn_mfr:
            by_mpn_mfr[(mpn, mfr)] = item
    return by_upc, by_mpn_mfr


def match_catalog(
    product: dict[str, Any],
    by_upc: dict[str, dict],
    by_mpn_mfr: dict[tuple[str, str], dict],
) -> dict[str, Any] | None:
    u = product.get("upc_norm") or normalize_upc(product.get("upc"))[0]
    if u and u in by_upc:
        return by_upc[u]
    mpn = product.get("mpn_norm") or canonicalize_mpn(product.get("mpn"))
    mfr = (product.get("manufacturer") or "").strip().upper()
    if mpn and mfr and (mpn, mfr) in by_mpn_mfr:
        return by_mpn_mfr[(mpn, mfr)]
    return None


def authorized_supplier_title(catalog: dict[str, Any], product: dict[str, Any]) -> str:
    for key in ("RandmarTitle", "Title"):
        val = str(catalog.get(key) or "").strip()
        if val:
            return val
    brand = str(product.get("manufacturer") or catalog.get("ManufacturerName") or "").strip()
    mpn = str(product.get("mpn_norm") or product.get("mpn") or catalog.get("MPN") or "").strip()
    return f"{brand} {mpn}".strip() or str(product.get("sku") or "")


def authorized_caption(catalog: dict[str, Any], supplier_title: str) -> str:
    cap = str(catalog.get("VoiceoverCaption") or "").strip()
    if cap:
        return cap
    title = str(catalog.get("Title") or "").strip()
    if title:
        return title
    return supplier_title


def ai_optimize_title(
    catalog: dict[str, Any],
    product: dict[str, Any],
    supplier_title: str,
) -> str:
    """Factual title optimization from authorized catalog fields only."""
    brand = str(catalog.get("ManufacturerName") or product.get("manufacturer") or "").strip()
    mpn = str(catalog.get("MPN") or product.get("mpn") or "").strip()
    ptype = str(catalog.get("ProductType") or product.get("product_type") or "").strip()
    full_title = str(catalog.get("Title") or "").strip()

    # Prefer catalog Title when present; lightly normalize Brand-first
    if full_title:
        title = full_title
        if brand and brand.lower() not in title.lower()[: max(len(brand) + 5, 20)]:
            title = f"{brand} {title}"
    else:
        parts = [p for p in (brand, supplier_title) if p]
        title = " ".join(parts) if parts else supplier_title
        if ptype and ptype.lower() not in title.lower():
            title = f"{title} {ptype}"
        if mpn and mpn.lower() not in title.lower():
            title = f"{title} {mpn}"

    return _trunc80(title)


def ai_restructure_description(
    catalog: dict[str, Any],
    product: dict[str, Any],
    supplier_title: str,
    caption: str,
) -> str:
    """Restructure SAME authorized facts into a clearer listing description.

    Never invents accessories, colour, dimensions, or features absent from source.
    """
    brand = str(catalog.get("ManufacturerName") or product.get("manufacturer") or "").strip()
    mpn = str(catalog.get("MPN") or product.get("mpn") or "").strip()
    upc = str(
        catalog.get("UPC") or product.get("upc_norm") or product.get("upc") or ""
    ).strip()
    ptype = str(catalog.get("ProductType") or product.get("product_type") or "").strip()
    full_title = str(catalog.get("Title") or supplier_title).strip()

    bullets: list[str] = []
    if brand:
        bullets.append(f"Brand: {brand}")
    if mpn:
        bullets.append(f"MPN: {mpn}")
    if upc:
        bullets.append(f"UPC: {upc}")
    if ptype:
        bullets.append(f"Type: {ptype}")
    bullets.append("Condition: New")

    # Optional unit facts only when catalog provides them (no invention)
    for label, key in (
        ("Weight", "UnitWeight"),
        ("Length", "UnitLength"),
        ("Width", "UnitWidth"),
        ("Height", "UnitHeight"),
    ):
        val = catalog.get(key)
        if val not in (None, "", 0, 0.0):
            bullets.append(f"{label}: {val}")

    parts = [full_title]
    if caption and caption.strip() and caption.strip() != full_title:
        # Keep authorized caption text intact (restructured layout only)
        parts.append("")
        parts.append(caption.strip())
    parts.append("")
    parts.append("Product details:")
    parts.extend(f"• {b}" for b in bullets)
    parts.append("")
    parts.append("Ships from authorized Canadian distributor inventory.")
    return "\n".join(parts)


def apply_item_specifics(
    draft: dict[str, Any],
    *,
    brand: str | None,
    mpn: str | None,
    upc: str | None,
    product_type: str | None,
) -> None:
    product = draft["inventory_item"]["product"]
    aspects: dict[str, list[str]] = {}
    if brand:
        aspects["Brand"] = [brand]
        product["brand"] = brand
    if mpn:
        aspects["MPN"] = [mpn]
        product["mpn"] = mpn
    if upc:
        aspects["UPC"] = [upc]
        product["upc"] = [upc]
    if product_type:
        aspects["Type"] = [product_type]
    product["aspects"] = aspects


def build_variant_draft(
    *,
    product: dict[str, Any],
    catalog: dict[str, Any],
    creative_variant: str,
    creative_version_id: str,
    stock_buffer: int,
    marketplace_id: str,
    auth: dict[str, Any],
    ab_twin_of: str | None = None,
) -> dict[str, Any]:
    supplier_title = authorized_supplier_title(catalog, product)
    caption = authorized_caption(catalog, supplier_title)
    brand = str(catalog.get("ManufacturerName") or product.get("manufacturer") or "").strip() or None
    mpn = str(catalog.get("MPN") or product.get("mpn_norm") or product.get("mpn") or "").strip() or None
    upc = str(
        catalog.get("UPC") or product.get("upc_norm") or product.get("upc") or ""
    ).strip() or None
    ptype = str(
        catalog.get("ProductType") or product.get("product_type") or product.get("category") or ""
    ).strip() or None

    # Enrich weight from catalog when DB missing (authorized UnitWeight only)
    product_for_draft = dict(product)
    product_for_draft["sell_comp"] = auth["sell_price"]
    if not product_for_draft.get("unit_weight") and catalog.get("UnitWeight") not in (None, ""):
        try:
            product_for_draft["unit_weight"] = float(catalog["UnitWeight"])
        except (TypeError, ValueError):
            pass
    if brand:
        product_for_draft["manufacturer"] = brand
    if mpn:
        product_for_draft["mpn"] = mpn
        product_for_draft["mpn_norm"] = canonicalize_mpn(mpn) or mpn
    if upc:
        product_for_draft["upc"] = upc
        u, _ = normalize_upc(upc)
        if u:
            product_for_draft["upc_norm"] = u
    if ptype:
        product_for_draft["product_type"] = ptype

    if creative_variant == CREATIVE_AI_ENHANCED:
        title = ai_optimize_title(catalog, product, supplier_title)
        description = ai_restructure_description(catalog, product, supplier_title, caption)
    else:
        title = _trunc80(supplier_title)
        description = caption

    product_for_draft["title"] = title
    draft = build_inventory_draft(
        product_for_draft,
        stock_buffer=stock_buffer,
        marketplace_id=marketplace_id,
    )
    draft["inventory_item"]["product"]["title"] = title[:80]
    draft["inventory_item"]["product"]["description"] = description
    draft["offer"]["listingDescription"] = description
    apply_item_specifics(draft, brand=brand, mpn=mpn, upc=upc, product_type=ptype)

    draft["creative_variant"] = creative_variant
    draft["creative_version_id"] = creative_version_id
    draft["pipeline_source"] = PIPELINE_RANDMAR_FIRST
    draft["cohort"] = COHORT_SAFE_NATIONWIDE
    draft["comparison_cohort_id"] = COMPARISON_ID
    draft["snapshot_id"] = SNAPSHOT_ID
    draft["publish"] = False
    draft["draft"] = True
    draft["live_listings_enabled"] = False
    draft["ebay_sandbox_publish_enabled"] = False
    draft["imageUrls"] = []
    draft["image_enhancement_status"] = IMAGE_BLOCK_STATUS
    draft["authorization"] = {
        "map_ok": auth["map_ok"],
        "channel_ok": auth["channel_ok"],
        "needs_manual_channel_review": auth["needs_manual_channel_review"],
        "flags": auth["authorization_flags"],
    }
    draft["catalog_match"] = {
        "randmar_sku": catalog.get("RandmarSKU"),
        "matched_via": "upc_or_mpn_manufacturer",
        "has_voiceover_caption": bool(str(catalog.get("VoiceoverCaption") or "").strip()),
    }
    draft.update(ab_metric_placeholders())
    if ab_twin_of:
        draft["ab_twin_of"] = ab_twin_of
    return draft


def move_destination_sensitive(drafts_root: Path) -> int:
    """Move flat DESTINATION_SENSITIVE drafts into destination_sensitive/."""
    dest_dir = drafts_root / "destination_sensitive"
    dest_dir.mkdir(parents=True, exist_ok=True)
    moved = 0
    for path in sorted(drafts_root.glob("*.json")):
        if path.name.startswith("_"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("cohort") != COHORT_DESTINATION_SENSITIVE:
            continue
        data["creative_batch_tag"] = DEST_HELD_TAG
        data["publish"] = False
        target = dest_dir / path.name
        target.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        path.unlink()
        moved += 1
    return moved


def main() -> int:
    settings = get_settings()
    # Safety: never run with live publish gates on
    if (
        settings.live_listings_enabled
        or settings.ebay_sandbox_publish_enabled
        or settings.supplier_orders_enabled
    ):
        print(
            "REFUSED: live gate is ON "
            "(LIVE_LISTINGS_ENABLED / EBAY_SANDBOX_PUBLISH_ENABLED / "
            "SUPPLIER_ORDERS_ENABLED must be false)",
            file=sys.stderr,
        )
        return 2

    data_dir = Path(settings.db_path).parent
    drafts_root = data_dir / "drafts" / "randmar_first"
    safe_dir = drafts_root / "safe_nationwide"
    dest_dir = drafts_root / "destination_sensitive"
    reports_dir = drafts_root / "creative_reports"
    for d in (safe_dir, dest_dir, reports_dir):
        d.mkdir(parents=True, exist_ok=True)

    cohort_path = (
        data_dir
        / "cohorts"
        / SNAPSHOT_ID
        / "randmar_first"
        / "SAFE_NATIONWIDE.json"
    )
    catalog_path = data_dir / "products_all.json"

    with cohort_path.open(encoding="utf-8") as f:
        safe_skus = [str(r["sku"]) for r in json.load(f)["rows"]]

    print(f"Loading catalog from {catalog_path} ...")
    by_upc, by_mpn_mfr = load_catalog(catalog_path)
    print(f"Catalog indexed: upc={len(by_upc)} mpn_mfr={len(by_mpn_mfr)}")

    moved_dest = move_destination_sensitive(drafts_root)
    print(f"Moved DESTINATION_SENSITIVE drafts: {moved_dest}")

    conn = init_db(settings.db_path)
    final_drafts = 0
    both_versions = 0
    ai_image_blocked = 0
    other_blockers: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []

    for sku in safe_skus:
        row = conn.execute("SELECT * FROM products WHERE sku=?", (sku,)).fetchone()
        if row is None:
            other_blockers.append({"sku": sku, "reason": "missing_product_row"})
            continue
        product = dict(row)

        # Prefer MAP/sell from legacy flat draft if present
        legacy_path = drafts_root / f"{sku}.json"
        legacy = None
        if legacy_path.exists():
            try:
                legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                legacy = None
        if legacy:
            try:
                price = float(
                    legacy.get("offer", {})
                    .get("pricingSummary", {})
                    .get("price", {})
                    .get("value")
                    or 0
                )
                if price > 0:
                    product["sell_comp"] = price
            except (TypeError, ValueError):
                pass
            try:
                qty = int(
                    legacy.get("inventory_item", {})
                    .get("availability", {})
                    .get("shipToLocationAvailability", {})
                    .get("quantity")
                )
                # qty was stock-buffer; restore approximate stock for rebuild
                product["stock"] = qty + int(settings.stock_buffer)
            except (TypeError, ValueError, KeyError):
                pass

        catalog = match_catalog(product, by_upc, by_mpn_mfr)
        if catalog is None:
            other_blockers.append({"sku": sku, "reason": "catalog_match_failed"})
            continue

        auth = authorize_sku(product)
        if not auth["map_ok"]:
            other_blockers.append(
                {
                    "sku": sku,
                    "reason": "map_ok_false",
                    "flags": auth["authorization_flags"],
                }
            )
            continue

        creative_version = f"cv-{sku[:8]}-{uuid.uuid4().hex[:8]}"
        original = build_variant_draft(
            product=product,
            catalog=catalog,
            creative_variant=CREATIVE_ORIGINAL_SUPPLIER,
            creative_version_id=creative_version,
            stock_buffer=settings.stock_buffer,
            marketplace_id=settings.ebay_marketplace_id,
            auth=auth,
        )
        twin = build_variant_draft(
            product=product,
            catalog=catalog,
            creative_variant=CREATIVE_AI_ENHANCED,
            creative_version_id=f"{creative_version}-ai",
            stock_buffer=settings.stock_buffer,
            marketplace_id=settings.ebay_marketplace_id,
            auth=auth,
            ab_twin_of=creative_version,
        )

        orig_path = safe_dir / f"{sku}.ORIGINAL_SUPPLIER.json"
        ai_path = safe_dir / f"{sku}.AI_ENHANCED.json"
        orig_path.write_text(
            json.dumps(original, indent=2, default=str), encoding="utf-8"
        )
        ai_path.write_text(json.dumps(twin, indent=2, default=str), encoding="utf-8")
        ai_image_blocked += 1  # all AI twins image-blocked by design

        flat = dict(original)
        flat["creative_variants"] = {
            CREATIVE_ORIGINAL_SUPPLIER: str(orig_path),
            CREATIVE_AI_ENHANCED: str(ai_path),
        }
        flat["ab_assignment"] = "A|B"
        flat["creative_variant"] = CREATIVE_ORIGINAL_SUPPLIER
        flat["creative_version_id"] = creative_version
        flat["image_enhancement_status"] = IMAGE_BLOCK_STATUS
        flat["imageUrls"] = []
        flat["publish"] = False
        flat_path = drafts_root / f"{sku}.json"
        flat_path.write_text(json.dumps(flat, indent=2, default=str), encoding="utf-8")

        asset_paths = [str(orig_path), str(ai_path), str(flat_path)]
        upsert_sku_metrics(
            sku,
            {
                "pipeline_source": PIPELINE_RANDMAR_FIRST,
                "creative_version_id": creative_version,
                "creative_variant": CREATIVE_ORIGINAL_SUPPLIER,
                "asset_paths": asset_paths,
                "ab_assignment": "A|B",
                "comparison_cohort_id": COMPARISON_ID,
            },
            settings=settings,
            conn=conn,
            source="batch_creative_safe_nationwide",
        )
        # title + cohort are shared product fields (not measurable-key gated)
        orig_title = original["inventory_item"]["product"]["title"]
        conn.execute(
            """
            UPDATE products
            SET title=?, cohort=?, pipeline_source=?, comparison_cohort_id=?,
                updated_at=datetime('now')
            WHERE sku=?
            """,
            (
                orig_title,
                COHORT_SAFE_NATIONWIDE,
                PIPELINE_RANDMAR_FIRST,
                COMPARISON_ID,
                sku,
            ),
        )

        final_drafts += 1
        both_versions += 1
        if len(samples) < 3:
            samples.append(
                {
                    "sku": sku,
                    "original_title": orig_title,
                    "ai_title": twin["inventory_item"]["product"]["title"],
                    "original_path": str(orig_path),
                    "ai_path": str(ai_path),
                    "flat_path": str(flat_path),
                }
            )

    conn.commit()
    conn.close()

    report = {
        "generated_at": _utc_now(),
        "snapshot_id": SNAPSHOT_ID,
        "pipeline_source": PIPELINE_RANDMAR_FIRST,
        "cohort": COHORT_SAFE_NATIONWIDE,
        "comparison_cohort_id": COMPARISON_ID,
        "publish": False,
        "live_listings_enabled": False,
        "ebay_sandbox_publish_enabled": False,
        "counts": {
            "safe_nationwide_skus": len(safe_skus),
            "final_drafts": final_drafts,
            "both_creative_versions": both_versions,
            "ai_image_twins_blocked_no_imagery": ai_image_blocked,
            "other_blockers": len(other_blockers),
            "destination_sensitive_moved": moved_dest,
        },
        "other_blockers_detail": other_blockers,
        "destination_sensitive_moved_count": moved_dest,
        "image_enhancement_status": IMAGE_BLOCK_STATUS,
        "samples": samples,
        "paths": {
            "safe_nationwide": str(safe_dir),
            "destination_sensitive": str(dest_dir),
            "creative_reports": str(reports_dir),
        },
    }
    report_path = (
        reports_dir / f"creative_batch_{SNAPSHOT_ID}_SAFE_NATIONWIDE.json"
    )
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report["counts"], indent=2))
    print(f"report_path={report_path}")
    return 0 if final_drafts == len(safe_skus) and not other_blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Draft eBay Inventory API-shaped JSON for listable SKUs.

NEVER publishes. LIVE_LISTINGS_ENABLED and EBAY_SANDBOX_PUBLISH_ENABLED stay off.
"""

from __future__ import annotations

from typing import Any, Mapping


def build_inventory_draft(
    product: Mapping[str, Any],
    *,
    stock_buffer: int = 2,
    marketplace_id: str = "EBAY_CA",
    currency: str = "CAD",
) -> dict[str, Any]:
    """Build a Sell Inventory + Offer shaped draft payload (local only)."""
    map_price = float(product.get("map") or 0.0)
    sell = float(product.get("sell_comp") or map_price or 0.0)
    if map_price > 0 and sell < map_price:
        sell = map_price
    stock = int(product.get("stock") or 0)
    qty = max(0, stock - int(stock_buffer))
    weight = float(product.get("unit_weight") or 0.0)
    title = (
        product.get("title")
        or f"{product.get('manufacturer') or ''} {product.get('mpn') or product.get('sku')}".strip()
    )
    sku = str(product.get("sku") or "")
    aspects: dict[str, list[str]] = {}
    if product.get("manufacturer"):
        aspects["Brand"] = [str(product["manufacturer"])]
    if product.get("mpn") or product.get("mpn_norm"):
        aspects["MPN"] = [str(product.get("mpn_norm") or product.get("mpn"))]
    if product.get("upc_norm") or product.get("upc"):
        aspects["UPC"] = [str(product.get("upc_norm") or product.get("upc"))]

    image_urls: list[str] = []
    raw_images = product.get("image_urls")
    if isinstance(raw_images, str) and raw_images.strip():
        import json as _json

        try:
            raw_images = _json.loads(raw_images)
        except Exception:
            raw_images = None
    if isinstance(raw_images, list):
        for item in raw_images:
            if isinstance(item, str) and item.startswith("http"):
                image_urls.append(item)
            elif isinstance(item, dict):
                u = item.get("url") or item.get("Url")
                if u:
                    image_urls.append(str(u))
    elif isinstance(product.get("image_url_list"), list):
        image_urls = [str(u) for u in product["image_url_list"] if u]

    inventory_item = {
        "sku": sku,
        "product": {
            "title": title[:80],
            "aspects": aspects,
            "upc": (
                [str(product.get("upc_norm") or product.get("upc"))]
                if (product.get("upc_norm") or product.get("upc"))
                else []
            ),
            "mpn": str(product.get("mpn_norm") or product.get("mpn") or "") or None,
            "brand": product.get("manufacturer"),
            "description": title,
            "imageUrls": image_urls,
        },
        "condition": "NEW",
        "availability": {
            "shipToLocationAvailability": {"quantity": qty}
        },
        "packageWeightAndSize": {
            "weight": {
                "value": weight if weight > 0 else 1.0,
                "unit": "POUND",
            }
        },
    }
    offer = {
        "sku": sku,
        "marketplaceId": marketplace_id,
        "format": "FIXED_PRICE",
        "availableQuantity": qty,
        "categoryId": "placeholder",
        "listingPolicies": {
            "fulfillmentPolicyId": "placeholder",
            "paymentPolicyId": "placeholder",
            "returnPolicyId": "placeholder",
        },
        "pricingSummary": {
            "price": {"value": f"{sell:.2f}", "currency": currency}
        },
        "listingDescription": title,
    }
    return {
        "draft": True,
        "publish": False,
        "live_listings_enabled": False,
        "ebay_sandbox_publish_enabled": False,
        "inventory_item": inventory_item,
        "offer": offer,
        "notes": (
            "Local draft only. Do not publish until LIVE_LISTINGS_ENABLED and "
            "end-to-end tests are approved. Price is MAP-floored."
        ),
    }

"""Exact supplier identity and present listing checks; never authorizes purchase."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import unicodedata


def normalized_text(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split()) if isinstance(value, str) else ""


def gtin(value):
    if not isinstance(value, str) or not value.isascii() or not value.isdigit() or len(value) not in (8, 12, 13, 14):
        return None
    digits = [int(c) for c in value]
    checksum = sum(n * (3 if i % 2 == 0 else 1) for i, n in enumerate(reversed(digits[:-1])))
    return value.zfill(14) if (checksum + digits[-1]) % 10 == 0 else None


def amount(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        return None
    return result if result.is_finite() and result >= 0 else None


def verify_identity(merchant_sku, inventory, supplier):
    if not isinstance(inventory, dict) or not isinstance(supplier, dict):
        return "malformed_product_identity"
    if inventory.get("sku") != merchant_sku or supplier.get("RandmarSKU") != merchant_sku:
        return "sku_mismatch"
    product = inventory.get("product") or {}
    if not isinstance(product, dict):
        return "malformed_product_identity"
    e_upcs = product.get("upc") or []
    if not isinstance(e_upcs, list):
        return "malformed_product_identity"
    supplier_upc = gtin(supplier.get("UPC"))
    ebay_upcs = {g for raw in e_upcs if (g := gtin(raw))}
    ebay_mpn, source_mpn = normalized_text(product.get("mpn")), normalized_text(supplier.get("MPN"))
    ebay_brand, source_brand = normalized_text(product.get("brand")), normalized_text(supplier.get("ManufacturerName"))
    if supplier_upc and ebay_upcs and supplier_upc not in ebay_upcs:
        return "upc_conflict"
    if ebay_mpn and source_mpn and ebay_mpn != source_mpn:
        return "mpn_conflict"
    if ebay_brand and source_brand and ebay_brand != source_brand:
        # Narrow identity alias, NOT channel authorization. HP's own Canadian
        # SU858A product page and W2020XC supplies brochure confirm the brand.
        # Require the catalog manufacturer ID plus BOTH independent identifiers.
        hp_canada = (source_brand == "hp canada" and ebay_brand == "hp"
                     and str(supplier.get("ManufacturerId")) == "25150"
                     and supplier_upc and supplier_upc in ebay_upcs
                     and ebay_mpn and ebay_mpn == source_mpn)
        if not hp_canada:
            return "brand_conflict"
    if supplier_upc and supplier_upc in ebay_upcs:
        return "exact_sku_and_gtin"
    if ebay_mpn and ebay_mpn == source_mpn and ebay_brand and ebay_brand == source_brand:
        return "exact_sku_mpn_brand"
    return "insufficient_identity_evidence"


def inspect_listing(*, merchant_sku, listing_id, inventory, offers, supplier, stock_buffer):
    identity = verify_identity(merchant_sku, inventory, supplier)
    def obj(value):
        return value if isinstance(value, dict) else {}
    supplier = obj(supplier)
    offer_rows = obj(offers).get("offers")
    offer_rows = offer_rows if isinstance(offer_rows, list) else []
    matched = [o for o in offer_rows if isinstance(o, dict) and
               str(obj(o.get("listing")).get("listingId")) == str(listing_id) and
               o.get("sku") == merchant_sku and o.get("marketplaceId") == "EBAY_CA" and
               o.get("status") == "PUBLISHED"]
    hold = []
    if identity not in {"exact_sku_and_gtin", "exact_sku_mpn_brand"}:
        hold.append(identity)
    if len(matched) != 1:
        hold.append("published_offer_not_uniquely_matched")
    row = matched[0] if len(matched) == 1 else {}
    price_data = obj(obj(row.get("pricingSummary")).get("price"))
    price = amount(price_data.get("value")) if price_data.get("currency") == "CAD" else None
    stock, cost, map_price = (amount(supplier.get(k)) for k in ("AvailableQuantity", "Price", "MAP"))
    qty = row.get("availableQuantity")
    if price is None or price <= 0 or cost is None or cost <= 0:
        hold.append("unknown_price_or_cost")
    if map_price is None:
        hold.append("map_policy_unresolved")
    elif price is not None and price < map_price:
        hold.append("listed_below_map")
    if type(stock_buffer) is not int or stock_buffer < 0:
        raise ValueError("Invalid stock buffer")
    if stock is None or stock != stock.to_integral_value():
        hold.append("invalid_supplier_stock")
    elif type(qty) is not int or qty < 0:
        hold.append("invalid_listing_quantity")
    elif qty > max(0, int(stock) - stock_buffer):
        hold.append("listed_quantity_exceeds_buffered_stock")
    if supplier.get("OpportunityOnly") is not False:
        hold.append("default_opportunity_not_confirmed")
    return {"merchant_sku": merchant_sku, "supplier_sku": supplier.get("RandmarSKU"),
            "listing_id": listing_id, "identity": identity,
            "mapping_verified": identity in {"exact_sku_and_gtin", "exact_sku_mpn_brand"} and len(matched) == 1,
            "listed_price_cad": None if price is None else str(price),
            "unit_cost_cad": None if cost is None else str(cost),
            "map_cad": None if map_price is None else str(map_price),
            "supplier_stock": None if stock is None else str(stock), "listed_quantity": qty,
            "observed_holds": hold, "fulfillment_enabled": False,
            "remaining_evidence": ["channel_permission", "return_risk", "buyer_shipping_quote", "full_order_economics"]}

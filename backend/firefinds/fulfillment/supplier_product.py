"""Strict normalization of Randmar's Product response, not its cart projection."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class SupplierProduct:
    sku: str
    cost: Decimal
    map_price: Decimal
    stock: int


def nonnegative_amount(value):
    if isinstance(value, bool) or value is None:
        raise ValueError("Missing monetary amount")
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Invalid monetary amount") from None
    if not amount.is_finite() or amount < 0:
        raise ValueError("Invalid monetary amount")
    return amount


def parse_supplier_product(raw, expected_sku):
    if not isinstance(raw, dict) or raw.get("RandmarSKU") != expected_sku:
        raise ValueError("Supplier product identity mismatch")
    if raw.get("AvailableToBuy") is not True or raw.get("OpportunityOnly") is not False:
        raise ValueError("Supplier product purchase restricted")
    distribution = raw.get("Distribution")
    if not isinstance(distribution, dict) or distribution.get("Currency") != "CAD":
        raise ValueError("Supplier currency unresolved")
    cost = nonnegative_amount(distribution.get("Price"))
    map_price = nonnegative_amount(distribution.get("MAP"))
    if raw.get("MAP") is not None and nonnegative_amount(raw["MAP"]) != map_price:
        raise ValueError("Conflicting supplier MAP")
    inventory = distribution.get("Inventory")
    if not isinstance(inventory, list) or not inventory:
        raise ValueError("Supplier stock unresolved")
    stock, seen = 0, set()
    for row in inventory:
        if not isinstance(row, dict) or row.get("RandmarSKU") != expected_sku:
            raise ValueError("Inventory identity mismatch")
        warehouse, quantity = row.get("WarehouseId"), row.get("AvailableQuantity")
        if not isinstance(warehouse, str) or not warehouse or warehouse in seen:
            raise ValueError("Warehouse identity unresolved")
        seen.add(warehouse)
        if type(quantity) is not int or quantity < 0:
            raise ValueError("Invalid supplier stock")
        if row.get("Status") == "Active" and row.get("Country") == "CA":
            stock += quantity
    return SupplierProduct(expected_sku, cost, map_price, stock)

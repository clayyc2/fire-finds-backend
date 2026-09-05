import copy
from decimal import Decimal as D

import pytest

from firefinds.fulfillment.supplier_product import parse_supplier_product


@pytest.fixture
def product():
    return {"RandmarSKU": "R1", "AvailableToBuy": True, "OpportunityOnly": False,
            "MAP": 51.99, "Distribution": {"Currency": "CAD", "Price": 17.65, "MAP": 51.99,
                "Inventory": [{"RandmarSKU": "R1", "WarehouseId": "TOR", "AvailableQuantity": 4,
                               "Status": "Active", "Country": "CA"}]}}


def test_real_product_projection(product):
    parsed = parse_supplier_product(product, "R1")
    assert (parsed.cost, parsed.map_price, parsed.stock) == (D("17.65"), D("51.99"), 4)


@pytest.mark.parametrize("key,value", [("AvailableToBuy", False), ("AvailableToBuy", None),
    ("OpportunityOnly", True), ("OpportunityOnly", None), ("RandmarSKU", "other"), ("MAP", 1)])
def test_restricted_or_mismatched_product(product, key, value):
    product[key] = value
    with pytest.raises(ValueError):
        parse_supplier_product(product, "R1")


@pytest.mark.parametrize("value", [None, True, "NaN", "Infinity", -1, "invalid"])
def test_invalid_money(product, value):
    product["Distribution"]["Price"] = value
    with pytest.raises(ValueError):
        parse_supplier_product(product, "R1")


def test_duplicate_warehouse_does_not_double_stock(product):
    product["Distribution"]["Inventory"] *= 2
    with pytest.raises(ValueError):
        parse_supplier_product(product, "R1")


@pytest.mark.parametrize("value", [True, -1, None, 4.5])
def test_invalid_stock(product, value):
    product["Distribution"]["Inventory"][0]["AvailableQuantity"] = value
    with pytest.raises(ValueError):
        parse_supplier_product(product, "R1")


def test_no_inactive_or_foreign_stock(product):
    first = product["Distribution"]["Inventory"][0]
    foreign = copy.deepcopy(first)
    foreign.update(WarehouseId="US", Country="US")
    first["Status"] = "Inactive"
    product["Distribution"]["Inventory"].append(foreign)
    assert parse_supplier_product(product, "R1").stock == 0

from decimal import Decimal as D

import pytest

from firefinds.fulfillment.shipping_quote import parse_shipping_quotes


def wrap(**fields):
    return {"ShippingMethods": {"Methods": [{"MethodId": "PCNNSR", "Label": "Canada Post",
        "Fees": 10, "RealShippingCharges": 12.5, "Discount": 5, **fields}]}}


def test_conservative_quote_not_unverified_discount():
    quote, = parse_shipping_quotes(wrap())
    assert quote.charge_upper_bound == D("12.5")
    assert not hasattr(quote, "delivery_date")


@pytest.mark.parametrize("field,value", [("Fees", None), ("RealShippingCharges", None),
    ("Fees", "NaN"), ("Fees", -1), ("Fees", True), ("MethodId", ""), ("Label", None)])
def test_incomplete_quote_is_not_free(field, value):
    with pytest.raises(ValueError):
        parse_shipping_quotes(wrap(**{field: value}))


def test_duplicate_ids_fail_closed():
    raw = wrap()
    raw["ShippingMethods"]["Methods"] *= 2
    with pytest.raises(ValueError):
        parse_shipping_quotes(raw)


@pytest.mark.parametrize("raw", [None, {}, {"ShippingMethods": {}}, {"ShippingMethods": {"Methods": []}}])
def test_empty_quote_held(raw):
    with pytest.raises(ValueError):
        parse_shipping_quotes(raw)

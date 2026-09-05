from copy import deepcopy
from decimal import Decimal as D

import pytest

from firefinds.fulfillment.order_money import parse_order_money


def cad(value):
    return {"currency": "CAD", "value": str(value)}


@pytest.fixture
def order():
    return {"orderPaymentStatus": "PAID", "paymentSummary": {"refunds": []},
        "lineItems": [{"quantity": 2, "lineItemCost": cad(100),
            "discountedLineItemCost": cad(90), "taxes": [{"taxType": "GST", "amount": cad(5)}],
            "ebayCollectAndRemitTaxes": [{"taxType": "GST", "amount": cad(5)}]}],
        "pricingSummary": {"priceSubtotal": cad(100), "priceDiscount": cad(-10),
            "deliveryCost": cad(15), "deliveryDiscount": cad(-5), "tax": cad(5), "total": cad(105)},
        "totalFeeBasisAmount": cad(105), "totalMarketplaceFee": cad(15)}


def test_shipping_is_revenue_but_not_item_map_price_and_taxes_count_once(order):
    parsed = parse_order_money(order)
    assert parsed.revenue == D(100)
    assert parsed.item_revenue == D(90)
    assert parsed.unit_revenue == D(50)
    assert parsed.unit_item_price == D(45)
    assert parsed.tax == D(5)
    assert parsed.fee_basis == D(105)
    assert parsed.accrued_marketplace_fees == D(15)


def test_fee_basis_never_smaller_than_tax_inclusive_gross(order):
    order["totalFeeBasisAmount"] = cad(90)
    assert parse_order_money(order).fee_basis == D(105)
    order["totalFeeBasisAmount"] = cad(110)
    assert parse_order_money(order).fee_basis == D(110)


def test_collect_remit_missing_from_summary_is_still_excluded(order):
    del order["pricingSummary"]["tax"]
    assert parse_order_money(order).revenue == D(100)


def test_tax_only_in_summary(order):
    del order["lineItems"][0]["taxes"]
    del order["lineItems"][0]["ebayCollectAndRemitTaxes"]
    assert parse_order_money(order).tax == D(5)


@pytest.mark.parametrize("field,value", [("priceDiscount", 10), ("deliveryDiscount", 5),
    ("deliveryCost", -1), ("priceSubtotal", 99), ("total", 100), ("tax", 6),
    ("adjustment", 1), ("fee", 1), ("deliveryDiscount", -16), ("priceDiscount", -101)])
def test_conflicting_money_holds(order, field, value):
    order["pricingSummary"][field] = cad(value)
    with pytest.raises(ValueError):
        parse_order_money(order)


@pytest.mark.parametrize("value", [None, {}, {"value": "100", "currency": "USD"},
    cad("NaN"), cad("Infinity"), cad("1e100"), cad("0.001"), cad("invalid"),
    {"value": True, "currency": "CAD"}, {"value": 100, "currency": "CAD"}])
def test_malformed_money_never_becomes_zero(order, value):
    order["pricingSummary"]["deliveryCost"] = value
    with pytest.raises(ValueError):
        parse_order_money(order)


@pytest.mark.parametrize("qty", [0, -1, True, 1.5, None])
def test_bad_quantity(order, qty):
    order["lineItems"][0]["quantity"] = qty
    with pytest.raises(ValueError):
        parse_order_money(order)


def test_refund_and_special_programs_are_not_silently_normalized(order):
    for changed in (
        {"paymentSummary": {"refunds": [{"refundStatus": "PENDING"}]}},
        {"orderPaymentStatus": "PARTIALLY_REFUNDED"}, {"program": {"anything": True}},
        {"paymentSummary": None}):
        with pytest.raises(ValueError):
            parse_order_money({**order, **changed})
    for field in ("refunds", "ebayCollectedCharges", "giftDetails"):
        other = deepcopy(order)
        other["lineItems"][0][field] = [{"unresolved": True}]
        with pytest.raises(ValueError):
            parse_order_money(other)


def test_conflicting_and_duplicate_taxes_hold(order):
    line = order["lineItems"][0]
    line["ebayCollectAndRemitTaxes"][0]["amount"] = cad(6)
    with pytest.raises(ValueError):
        parse_order_money(order)
    line["ebayCollectAndRemitTaxes"] = []
    line["taxes"] *= 2
    with pytest.raises(ValueError):
        parse_order_money(order)


def test_distinct_canadian_taxes_reconcile(order):
    line = order["lineItems"][0]
    line["ebayCollectAndRemitTaxes"].append({"taxType": "PROVINCE_SALES_TAX", "amount": cad(8)})
    order["pricingSummary"].update(tax=cad(13), total=cad(113))
    assert parse_order_money(order).tax == D(13)


def test_missing_free_shipping_amount_is_not_assumed_zero(order):
    del order["pricingSummary"]["deliveryCost"]
    with pytest.raises(ValueError):
        parse_order_money(order)


def test_optional_null_field_is_not_absence(order):
    order["pricingSummary"]["adjustment"] = None
    with pytest.raises(ValueError):
        parse_order_money(order)

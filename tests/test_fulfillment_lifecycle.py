import json
from pathlib import Path
from dataclasses import replace
from decimal import Decimal as D

import pytest

from firefinds.clients.ebay import EbayClient, EbayFulfillmentDisabled
from firefinds.clients.randmar import RandmarClient, SupplierOrdersDisabled
from firefinds.config import Settings
from firefinds.engine.models import Candidate
from firefinds.engine.order_ingest import OrderIngest
from firefinds.engine.order_poll import poll_orders
from firefinds.engine.services import Audit, OrderRouter
from firefinds.fulfillment.preview import prepare_fulfillment
from firefinds.fulfillment.tracking import prepare_tracking


def fixture_order():
    value = json.loads((Path(__file__).parent / "fixtures/ebay_paid_order.json").read_text())
    value["shippingAddress"]["primaryPhone"] = {"phoneNumber": "5550100"}
    return value


def shipment(order):
    return {"PONumber": order["orderId"], "OrderNumber": "FAKE-R1", "RandmarSKU": "SUPPLIER1",
            "QuantityShipped": 1, "TrackingNumber": "FIXTURE-NOT-REAL", "ShipVia": "R-CARRIER"}


def test_fixture_lifecycle_across_real_boundaries(monkeypatch, tmp_path):
    settings = Settings()
    order = fixture_order()
    ebay = EbayClient(settings)
    def read_only(method, path, **kwargs):
        assert method == "GET"
        return {"orders": [order], "total": 1}
    monkeypatch.setattr(ebay, "_sell_json", read_only)
    audit = Audit(tmp_path / "audit.jsonl")
    ingest = OrderIngest(settings, audit, tmp_path / "ingest.json")
    mapping = {order["lineItems"][0]["sku"]: "SUPPLIER1"}
    sweep = poll_orders(client=ebay, ingest=ingest, sku_mapping=mapping,
                        progress_path=tmp_path / "poll.json")
    assert sweep["complete"] and sweep["blocked"] == 0
    preview = prepare_fulfillment(
        settings=settings, order=order, sku_mapping=mapping,
        supplier=Candidate("SUPPLIER1", D("20"), D("10"), 10, channel_allowed=True),
        shipping_method_id="GROUND", unit_sale_revenue=D("80"), quote_observed_at=1000, now=1050)
    assert preview.allowed
    randmar = RandmarClient(settings)
    monkeypatch.setattr(randmar, "_request_json", lambda *a, **kw: pytest.fail("unexpected real supplier call"))
    with pytest.raises(SupplierOrdersDisabled):
        randmar.process_cart("fixture-cart", preview.payload)
    # Exercise the durable guard using an in-memory supplier ONLY. No API client
    # is passed to this enabled test configuration.
    ledger = OrderRouter(replace(settings, dry_run=False, global_kill_switch=False,
                                 supplier_orders_enabled=True), audit, tmp_path / "submit.json")
    calls = []
    def fake_supplier(_):
        calls.append(1)
        return {"OrderNumber": "FAKE-R1"}
    ledger.route({"order_id": order["orderId"]}, fake_supplier)
    assert ledger.route({"order_id": order["orderId"]}, fake_supplier) == "duplicate"
    assert len(calls) == 1
    tracking = prepare_tracking(order=order, supplier_sku="SUPPLIER1", supplier_order_number="FAKE-R1",
                                shipments=[shipment(order)], carrier_mapping={"R-CARRIER": "CanadaPost"})
    assert tracking["prepared"]
    body = tracking["payload"]
    with pytest.raises(EbayFulfillmentDisabled):
        ebay.create_shipping_fulfillment(order["orderId"], carrier_code=body["shippingCarrierCode"],
                                         tracking_number=body["trackingNumber"], line_items=body["lineItems"])
    assert not tracking["posted"]


@pytest.mark.parametrize("change,prepared", [
    ({}, True), ({"PONumber": "WRONG"}, False), ({"OrderNumber": "WRONG"}, False),
    ({"RandmarSKU": "WRONG"}, False), ({"QuantityShipped": 0}, False),
    ({"QuantityShipped": 2}, False), ({"QuantityShipped": "NaN"}, False),
    ({"TrackingNumber": None}, False), ({"ShipVia": "UNKNOWN"}, False),
])
def test_tracking_requires_complete_matching_evidence(change, prepared):
    order = fixture_order()
    result = prepare_tracking(order=order, supplier_sku="SUPPLIER1", supplier_order_number="FAKE-R1",
                              shipments=[dict(shipment(order), **change)], carrier_mapping={"R-CARRIER": "CanadaPost"})
    assert result["prepared"] is prepared and result["posted"] is False


def test_ambiguous_shipment_is_held():
    order = fixture_order()
    rows = [shipment(order), dict(shipment(order), TrackingNumber="OTHER")]
    result = prepare_tracking(order=order, supplier_sku="SUPPLIER1", supplier_order_number="FAKE-R1",
                              shipments=rows, carrier_mapping={"R-CARRIER": "CanadaPost"})
    assert result["prepared"] is False

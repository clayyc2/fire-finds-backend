from firefinds.fulfillment.randmar_checkout import (
    PATH_CART_PROCESS_NEW,
    RandmarOrderProbe,
    cart_name_for_ebay_order,
    pick_shipping_method_id,
    process_cart_input,
)


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def order_by_po(self, po: str):
        self.calls.append(f"GET_PO:{po}")
        raise RuntimeError("not found")

    def cart_add_item_default(self, cart, sku, *, quantity=1):
        self.calls.append(f"ADD:{cart}:{sku}:{quantity}")
        return {"ok": True}

    def cart_get(self, cart):
        self.calls.append(f"GET_CART:{cart}")
        return {"Name": cart, "Total": 10.0, "PartNumbers": ["SKU1"]}

    def cart_shipping_methods(self, cart, ship_to):
        self.calls.append(f"SHIP:{cart}")
        return {"ShippingMethods": {"Methods": [{"MethodId": "GND", "Label": "Ground", "Fees": 12.0}]}}

    def cart_delete(self, cart):
        self.calls.append(f"DEL:{cart}")
        return None

    def cart_process_new(self, *a, **k):
        raise AssertionError("ProcessNew must not be called")


def test_process_input_schema():
    body = process_cart_input(
        name="Buyer",
        street1="1 St",
        city="Calgary",
        province_code="ab",
        postal_code="T2P1J9",
        country_code="ca",
        po="12-345",
        contact_name="Buyer",
        contact_phone="4035550100",
        shipping_method_id="GND",
    )
    assert body["CountryCode"] == "CA"
    assert body["ProvinceCode"] == "AB"
    assert body["PO"] == "12-345"
    assert body["Street2"] == ""
    assert body["FutureOrderDate"] is None
    assert "ContactEmail" not in body


def test_probe_never_submits(settings):
    fake = FakeClient()
    report = RandmarOrderProbe(fake, settings).run(
        ebay_order_id="12-34567890123",
        sku="SKU1",
        qty=1,
        ship_to={
            "Name": "Buyer",
            "Street1": "1 St",
            "City": "Calgary",
            "Province": "AB",
            "PostalCode": "T2P1J9",
            "Country": "CA",
            "ContactName": "Buyer",
            "ContactPhone": "4035550100",
        },
    )
    assert report["process_called"] is False
    assert report["official_submit_path"] == PATH_CART_PROCESS_NEW
    assert report["process_cart_input"]["PO"] == "12-34567890123"
    assert report["shipping_method_id"] == "GND"
    assert "ADD:" in ",".join(fake.calls)
    assert not any("PROCESS" in c for c in fake.calls)
    held = [s for s in report["steps"] if s["name"] == "process_new_held"][0]
    assert held["called"] is False
    assert held["irreversible"] is True


def test_idempotent_po_stops(settings):
    class Existing(FakeClient):
        def order_by_po(self, po: str):
            return {"OrderNumber": "R-99", "PONumber": po}

    report = RandmarOrderProbe(Existing(), settings).run(
        ebay_order_id="E1",
        sku="SKU1",
        qty=1,
        ship_to={"Name": "A", "Street1": "1", "City": "X", "Province": "AB", "PostalCode": "T2P1J9", "Country": "CA"},
    )
    assert report["status"] == "ALREADY_ORDERED"
    assert report["process_called"] is False


def test_cart_name_and_method_pick():
    assert cart_name_for_ebay_order("12-34 56") == "ff-ebay-12-34-56"
    assert pick_shipping_method_id({"ShippingMethods": {"Methods": [{"MethodId": "X"}]}}) == "X"

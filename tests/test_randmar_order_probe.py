from firefinds.fulfillment.randmar_checkout import (
    PROCESS_FIELDS, build_process_cart_input, probe_order_path,
)

SHIP = {"name":"Buyer", "street1":"1 Main St", "city":"Edmonton",
        "province":"AB", "postal_code":"T5J 0N3", "country":"CA",
        "phone":"7805550100"}


def test_process_payload_is_exact_schema():
    body = build_process_cart_input(SHIP, ebay_order_id="EB-1", shipping_method_id="GROUND")
    assert set(body) == PROCESS_FIELDS and body["PO"] == "EB-1"


def test_probe_stops_before_submit():
    class Client:
        def __init__(self): self.calls=[]
        def get_order_by_po(self, po): self.calls.append("po"); return {}
        def cart_add_item_default(self, *a, **k): self.calls.append("add")
        def cart_get(self, *a): self.calls.append("get"); return {"Items": []}
        def cart_shipping_methods(self, *a):
            self.calls.append("ship")
            return {"ShippingMethods":{"Methods":[{"MethodId":"G","Fees":10}]}}
        def process_cart(self, *a, **k): raise AssertionError("must never submit")
    client=Client()
    result=probe_order_path(client, ebay_order_id="EB-1", sku="SKU", ship_to=SHIP)
    assert result["status"] == "held_before_submit"
    assert client.calls == ["po", "add", "get", "ship"]


def test_probe_short_circuits_existing_po():
    class Client:
        def get_order_by_po(self, po): return {"OrderNumber":"R1"}
        def __getattr__(self, name): raise AssertionError(name)
    assert probe_order_path(Client(), ebay_order_id="EB-1", sku="SKU", ship_to=SHIP)["status"] == "duplicate"

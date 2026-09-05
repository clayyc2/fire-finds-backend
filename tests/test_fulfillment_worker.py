"""Connected lifecycle with fake commerce adapters only; no network credentials."""
import copy
from dataclasses import replace
from decimal import Decimal as D
import json
from pathlib import Path

import pytest

from firefinds.config import Settings
from firefinds.engine.models import Candidate
from firefinds.engine.services import Audit
from firefinds.engine.order_ingest import map_ebay_order
from firefinds.fulfillment.randmar_checkout import cart_name_for
from firefinds.fulfillment.worker import CheckoutEvidence, FulfillmentWorker, order_fingerprint


class Ebay:
    def __init__(self, order):
        self.order, self.fulfillments, self.posts = order, [], 0
        self.post_timeout, self.read_change = False, False
        self.reads = 0

    def get_order(self, oid):
        self.reads += 1
        order = copy.deepcopy(self.order)
        if self.read_change and self.reads > 1:
            order["orderPaymentStatus"] = "FAILED"
        return order

    def list_shipping_fulfillments(self, oid):
        return {"fulfillments": self.fulfillments}

    def create_shipping_fulfillment(self, oid, *, carrier_code, tracking_number, line_items):
        self.posts += 1
        self.fulfillments.append({"shippingCarrierCode": carrier_code,
                                  "trackingNumber": tracking_number, "lineItems": line_items})
        if self.post_timeout:
            raise TimeoutError("simulated acceptance followed by timeout")
        return {"ok": True}


class Supplier:
    verified_po_absence_contract = True  # In-memory contract ONLY.

    def __init__(self, order, cart):
        self.order, self.cart, self.posts, self.accepted = order, cart, 0, False
        self.post_timeout, self.shipped = False, True

    def get_order_by_po(self, oid):
        if not self.accepted:
            return None
        return {"PONumber": oid, "OrderNumber": "FAKE-1", "OrderDetails": [
            {"RandmarSKU": "R1", "QuantityOrdered": 1}]}

    def cart_get(self, cart_name):
        return copy.deepcopy(self.cart)

    def process_cart(self, cart_name, payload):
        assert payload["PO"] == self.order["orderId"]
        assert not payload["AllowPartialShipment"]
        self.posts += 1
        self.accepted = True
        if self.post_timeout:
            raise TimeoutError("simulated supplier timeout")
        return {"OrderNumber": "FAKE-1"}

    def list_shipments(self):
        return [{"PONumber": self.order["orderId"], "OrderNumber": "FAKE-1",
                 "RandmarSKU": "R1", "QuantityShipped": 1, "TrackingNumber": "FAKE-TRACK",
                 "ShipVia": "FAKE-CARRIER"}] if self.shipped else []


@pytest.fixture
def rig(tmp_path):
    order = json.loads((Path(__file__).parent / "fixtures/ebay_paid_order.json").read_text())
    order["shippingAddress"]["primaryPhone"] = {"phoneNumber": "5550100"}
    order["cancelStatus"] = {"cancelState": "NONE_REQUESTED"}
    cart = {"Name": cart_name_for(order["orderId"]), "PartNumbers": [
        {"RandmarSKU": "R1", "AvailableToBuy": True, "OpportunityOnly": False,
         "Cart": {"Quantity": 1, "Price": 20}}]}
    evidence = CheckoutEvidence(order_fingerprint(order), 1000,
        Candidate("R1", D(20), D(10), 10, map_price=D(0), channel_allowed=True),
        D(80), "GROUND", cart, channel_evidence="fixture-approved", returns_evidence="fixture-approved",
        map_evidence="fixture-none", shipping_service_evidence="fixture-on-time", economics_evidence="fixture-costs",
        opportunity_only=False, currency="CAD", total_landed_cost=D(35), total_fee_upper_bound=D(12),
        catalog_observed_at=1000, supplier_charge_upper_bound_cad=D(35))
    ebay, supplier = Ebay(order), Supplier(order, copy.deepcopy(cart))
    settings = replace(Settings(), dry_run=False, global_kill_switch=False,
                       supplier_orders_enabled=True, ebay_tracking_updates_enabled=True)
    worker = FulfillmentWorker(settings=settings, ebay=ebay, supplier=supplier,
        audit=Audit(tmp_path / "audit.jsonl"), state_dir=tmp_path / "state",
        sku_mapping={order["lineItems"][0]["sku"]: "R1"},
        carrier_mapping={"FAKE-CARRIER": "CanadaPost"}, clock=lambda: 1050)
    return worker, evidence, ebay, supplier


def run(rig):
    worker, evidence, ebay, _ = rig
    return worker.run_order(ebay.order["orderId"], lambda _: evidence)


def test_connected_lifecycle_and_replay(rig):
    assert run(rig)["reason"] == "tracking_confirmation_pending"
    assert run(rig)["state"] == "FULFILLED"
    assert run(rig)["state"] == "FULFILLED"
    assert rig[2].posts == rig[3].posts == 1


@pytest.mark.parametrize("field,value", [
    ("channel_evidence", ""), ("returns_evidence", ""), ("map_evidence", ""),
    ("shipping_service_evidence", ""), ("economics_evidence", ""),
    ("opportunity_only", True), ("opportunity_only", None), ("currency", "USD"),
    ("observed_at", 0), ("observed_at", 2000), ("observed_at", float("nan")),
    ("total_landed_cost", D(1)), ("total_landed_cost", D(75)),
    ("total_fee_upper_bound", D(1)), ("total_fee_upper_bound", None),
    ("unit_sale_revenue", D("NaN")), ("order_fingerprint", "other-order"),
    ("catalog_observed_at", None), ("catalog_observed_at", 0), ("catalog_observed_at", 2000),
])
def test_missing_or_unsafe_evidence_never_buys(rig, field, value):
    worker, evidence, ebay, supplier = rig
    result = worker.run_order(ebay.order["orderId"], lambda _: replace(evidence, **{field: value}))
    assert result["state"] == "HELD"
    assert supplier.posts == ebay.posts == 0


@pytest.mark.parametrize("field,value", [("dry_run", True), ("global_kill_switch", True),
                                         ("supplier_orders_enabled", False)])
def test_dry_run_is_complete_preview_without_writes(rig, field, value):
    worker = rig[0]
    worker.s = replace(worker.s, **{field: value})
    assert run(rig)["state"] == "DRY_RUN_READY"
    assert rig[2].posts == rig[3].posts == 0


def test_order_refresh_detects_changed_payment(rig):
    rig[2].read_change = True
    assert run(rig)["reason"] == "order_changed_before_submission"
    assert rig[3].posts == 0


def test_cart_refresh_detects_price_drift(rig):
    rig[3].cart["PartNumbers"][0]["Cart"]["Price"] = 30
    assert run(rig)["reason"] == "cart_changed_before_submission"
    assert rig[3].posts == 0


def test_unverified_supplier_absence_does_not_buy(rig):
    rig[3].verified_po_absence_contract = False
    assert run(rig)["reason"] == "supplier_po_absence_contract_unverified"
    assert rig[3].posts == 0


def test_supplier_timeout_reconciles_instead_of_rebuying(rig):
    rig[3].post_timeout = True
    assert run(rig)["state"] == "HELD"
    assert run(rig)["reason"] == "tracking_confirmation_pending"
    assert run(rig)["state"] == "FULFILLED"
    assert rig[3].posts == rig[2].posts == 1


def test_tracking_timeout_reconciles_without_reposting(rig):
    rig[2].post_timeout = True
    assert run(rig)["reason"] == "tracking_reconciliation_required"
    assert run(rig)["state"] == "FULFILLED"
    assert rig[2].posts == rig[3].posts == 1


def test_unknown_submission_never_released_by_empty_lookup(rig):
    rig[3].post_timeout = True
    assert run(rig)["state"] == "HELD"
    rig[3].accepted = False
    for _ in range(3):
        assert run(rig)["reason"] == "supplier_reconciliation_required"
    assert rig[3].posts == 1


def test_missing_evidence_and_shipment_wait(rig):
    worker, _, ebay, supplier = rig
    assert worker.run_order(ebay.order["orderId"])["state"] == "HELD"
    supplier.shipped = False
    assert run(rig)["state"] == "AWAITING_SHIPMENT"
    assert run(rig)["state"] == "AWAITING_SHIPMENT"
    assert supplier.posts == 1 and ebay.posts == 0


def test_logs_and_state_do_not_contain_buyer_details(rig):
    run(rig)
    contents = "".join(p.read_text() for p in rig[0].root.parent.rglob("*") if p.is_file())
    assert "5550100" not in contents
    assert map_ebay_order(rig[2].order).ship_to["Street1"] not in contents


def test_crash_after_supplier_acceptance_requires_reconciliation(rig):
    supplier = rig[3]
    original = supplier.process_cart
    def crash(*args):
        original(*args)
        raise KeyboardInterrupt()
    supplier.process_cart = crash
    with pytest.raises(KeyboardInterrupt):
        run(rig)
    assert run(rig)["reason"] == "tracking_confirmation_pending"
    assert supplier.posts == 1


def test_unknown_tracking_not_found_does_not_retry(rig):
    rig[2].post_timeout = True
    assert run(rig)["reason"] == "tracking_reconciliation_required"
    rig[2].fulfillments = []
    for _ in range(3):
        assert run(rig)["reason"] == "tracking_reconciliation_required"
    assert rig[2].posts == 1


def test_corrupt_submission_state_is_not_reset(rig):
    rig[0].root.mkdir()
    (rig[0].root / "submissions.json").write_text('{"broken": 3}')
    assert run(rig)["state"] == "HELD"
    assert rig[3].posts == 0


def test_existing_conflicting_tracking_is_not_overwritten(rig):
    rig[2].fulfillments = [{"trackingNumber": "MANUAL-TRACKING"}]
    assert run(rig)["reason"] == "existing_tracking_conflict"
    assert rig[2].posts == 0


def test_changed_purchased_line_is_held_without_repurchase(rig):
    rig[3].shipped = False
    assert run(rig)["state"] == "AWAITING_SHIPMENT"
    rig[2].order["lineItems"][0]["quantity"] = 2
    assert run(rig)["reason"] == "purchased_order_line_changed"
    assert rig[3].posts == 1


def test_cancellation_after_purchase_raises_hold(rig):
    rig[3].shipped = False
    assert run(rig)["state"] == "AWAITING_SHIPMENT"
    rig[2].order["cancelStatus"]["cancelState"] = "CANCEL_REQUESTED"
    assert run(rig)["reason"] == "purchased_order_cancellation_needs_review"


def test_missing_cancellation_status_is_not_permission_to_buy(rig):
    rig[2].order.pop("cancelStatus")
    assert run(rig)["reason"] == "cancellation_status_unresolved"
    assert rig[3].posts == 0


def test_cash_cap_holds_before_supplier_submission_intent(rig):
    rig[0].budget.limit = D(10)
    assert run(rig)["reason"] == "daily_supplier_spend_limit"
    assert rig[3].posts == 0
    assert not (rig[0].root / "submissions.json").exists()


def test_fulfillment_checks_floor_not_new_competitor_asking_price(rig):
    worker, evidence, ebay, _ = rig
    evidence = replace(evidence, supplier=replace(evidence.supplier, competitor_price=D(300)))
    assert worker.run_order(ebay.order["orderId"], lambda _: evidence)["reason"] == "tracking_confirmation_pending"


def test_missing_cash_quote_is_held(rig):
    worker, evidence, ebay, supplier = rig
    evidence = replace(evidence, supplier_charge_upper_bound_cad=None)
    assert worker.run_order(ebay.order["orderId"], lambda _: evidence)["reason"] == "supplier_cash_upper_bound_unresolved"
    assert supplier.posts == 0

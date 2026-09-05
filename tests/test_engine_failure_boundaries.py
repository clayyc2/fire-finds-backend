import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal as D
from pathlib import Path
from threading import Event
from dataclasses import replace

import pytest

from firefinds.config import Settings
from firefinds.engine.capacity_live import parse_privilege_payload
from firefinds.engine.models import Candidate, Decision
from firefinds.engine.order_ingest import BLOCKED, ROUTED_OFF, OrderIngest, map_ebay_order
from firefinds.engine.services import Audit, CapacityManager, OpportunityEngine, OrderRouter


def live_settings():
    # Only used with fake callbacks. These tests make no network requests.
    return Settings(dry_run=False, global_kill_switch=False, supplier_orders_enabled=True)


def test_timeout_never_resubmits_after_restart(tmp_path):
    calls = []
    def uncertain(order):
        calls.append(order)
        raise TimeoutError("response lost after supplier accepted")
    path = tmp_path / "orders.json"
    audit = Audit(tmp_path / "audit.jsonl")
    with pytest.raises(TimeoutError):
        OrderRouter(live_settings(), audit, path).route({"order_id": "1"}, uncertain)
    assert OrderRouter(live_settings(), audit, path).route({"order_id": "1"}, uncertain) == "reconciliation-required"
    assert len(calls) == 1


def test_crash_during_submit_never_resubmits(tmp_path):
    def crash(order):
        raise KeyboardInterrupt()
    path = tmp_path / "orders.json"
    audit = Audit(tmp_path / "audit.jsonl")
    with pytest.raises(KeyboardInterrupt):
        OrderRouter(live_settings(), audit, path).route({"order_id": "1"}, crash)
    assert json.loads(path.read_text())["1"]["state"] == "SUBMITTING"
    assert OrderRouter(live_settings(), audit, path).route({"order_id": "1"}, crash) == "reconciliation-required"


def test_concurrent_workers_submit_once(tmp_path):
    started, release = Event(), Event()
    calls = []
    def submit(order):
        calls.append(order)
        started.set()
        assert release.wait(5)
        return "R1"
    audit = Audit(tmp_path / "audit.jsonl")
    path = tmp_path / "orders.json"
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(OrderRouter(live_settings(), audit, path).route, {"order_id": "1"}, submit)
        assert started.wait(5)
        try:
            second = pool.submit(OrderRouter(live_settings(), audit, path).route, {"order_id": "1"}, submit)
            assert second.result(timeout=5) == "reconciliation-required"
        finally:
            release.set()
        assert first.result(timeout=5) == "R1"
    assert len(calls) == 1


def test_missing_or_corrupt_checkpoint_refuses(tmp_path):
    audit = Audit(tmp_path / "audit.jsonl")
    called = []
    with pytest.raises(ValueError):
        OrderRouter(live_settings(), audit).route({"order_id": "1"}, called.append)
    path = tmp_path / "broken.json"
    path.write_text("{")
    with pytest.raises(ValueError):
        OrderRouter(live_settings(), audit, path).route({"order_id": "1"}, called.append)
    assert not called


def test_legacy_submission_ledger_still_prevents_duplicates(tmp_path):
    path = tmp_path / "orders.json"
    path.write_text('["1"]')
    assert OrderRouter(live_settings(), Audit(tmp_path / "audit.jsonl"), path).route(
        {"order_id": "1"}, lambda _: pytest.fail("duplicate")) == "duplicate"


def test_capacity_counts_units_value_headroom_and_existing_usage():
    s = Settings(monthly_item_limit=10, monthly_value_limit_cad=200, capacity_headroom_pct=.1)
    decisions = [Decision("A", True, "PASS", price=D("30"), quantity=10)]
    result = CapacityManager(s).select(decisions, used_items=2, used_value=D("100"))
    assert result[0].quantity == 2  # 180 total budget - 100 used => 2 at 30
    assert result[0].quantity * result[0].price + 100 <= 180


@pytest.mark.parametrize("items,amount", [(None, None), (0, 100), (5, 0), (5, None), (None, 100)])
def test_unknown_and_zero_capacity_never_mean_unlimited(items, amount):
    manager = CapacityManager(Settings(), live_item_limit=items, live_value_limit_cad=amount)
    assert manager.select([Decision("A", True, "PASS", price=D("10"), quantity=1)]) == []


def test_duplicate_skus_do_not_double_stock():
    manager = CapacityManager(Settings(monthly_item_limit=100, monthly_value_limit_cad=1000))
    d = Decision("A", True, "PASS", price=D("10"), quantity=2)
    assert sum(x.quantity for x in manager.select([d, d])) == 2


@pytest.mark.parametrize("quantity,value,currency", [("1.5", "2", "CAD"), (-1, "2", "CAD"), (2, "NaN", "CAD"), (2, "Infinity", "CAD"), (2, "2", "USD")])
def test_invalid_privilege_is_not_usable_capacity(quantity, value, currency):
    snap = parse_privilege_payload({"sellingLimit": {"quantity": quantity, "amount": {"value": value, "currency": currency}}})
    assert not snap.has_live_cap


def test_safe_price_cannot_be_cut_below_map_or_target():
    settings = Settings(target_profit_pct=.25)
    c = Candidate("A", D("20"), D("10"), 10, map_price=D("70"), competitor_price=D("69"), channel_allowed=True)
    decision = OpportunityEngine(settings).evaluate(c)
    assert not decision.allowed
    assert decision.price >= 70
    c = Candidate("A", D("20"), D("10"), 10, channel_allowed=True)
    decision = OpportunityEngine(settings).evaluate(c)
    raw_profit = decision.price * (1-D(str(settings.ebay_fee_rate))) - D(str(settings.ebay_fee_fixed)) - 30
    assert raw_profit / decision.price >= D(".25")


def paid_order():
    return json.loads((Path(__file__).parent / "fixtures/ebay_paid_order.json").read_text())


@pytest.mark.parametrize("change,reason", [
    ({"orderPaymentStatus": "PENDING"}, "payment_not_confirmed"),
    ({"orderFulfillmentStatus": "FULFILLED"}, "fulfillment_not_new"),
    ({"cancelStatus": {"cancelState": "CANCEL_REQUESTED"}}, "cancellation_pending_or_complete"),
    ({"lineItems": [{"legacyItemId": "123", "quantity": 1}]}, "unmapped_sku"),
    ({"lineItems": [{"sku": "A", "quantity": 0}]}, "invalid_quantity"),
    ({"lineItems": [{"sku": "A", "quantity": 1.5}]}, "invalid_quantity"),
    ({"lineItems": [{"sku": "A", "quantity": 1}, {"sku": "B", "quantity": 1}]}, "single_line_order_required"),
    ({"shippingAddress": {}}, "incomplete_shipping_address"),
])
def test_invalid_order_is_blocked(change, reason):
    order = paid_order()
    order.update(change)
    result = map_ebay_order(order)
    assert result.state == BLOCKED and result.reason == reason


def test_unpaid_order_can_be_reconsidered_when_paid(tmp_path):
    order = paid_order()
    order["orderPaymentStatus"] = "PENDING"
    ingest = OrderIngest(Settings(), Audit(tmp_path / "audit.jsonl"), tmp_path / "orders.json")
    assert ingest.ingest(order).state == BLOCKED
    order["orderPaymentStatus"] = "PAID"
    assert ingest.ingest(order).state == ROUTED_OFF


def test_stale_ingest_instances_preserve_other_orders(tmp_path):
    args = (Settings(), Audit(tmp_path / "audit.jsonl"), tmp_path / "orders.json")
    first, second = OrderIngest(*args), OrderIngest(*args)
    order = paid_order()
    first.ingest(order)
    order["orderId"] = "SECOND"
    second.ingest(order)
    assert len(json.loads((tmp_path / "orders.json").read_text())) == 2


def test_reconciliation_requires_exact_po_and_never_releases_for_retry(tmp_path):
    path = tmp_path / "orders.json"
    path.write_text(json.dumps({"E1": {"state": "UNKNOWN"}}))
    router = OrderRouter(live_settings(), Audit(tmp_path / "audit.jsonl"), path)
    assert router.reconcile("E1", lambda _: {}) == "reconciliation-required"
    assert router.reconcile("E1", lambda _: {"OrderNumber": "R2", "PONumber": "E2"}) == "reconciliation-required"
    assert router.reconcile("E1", lambda _: {"OrderNumber": "R1", "PONumber": "E1"}) == "reconciled"
    assert router.route({"order_id": "E1"}, lambda _: pytest.fail("resubmission")) == "duplicate"
    assert json.loads(path.read_text())["E1"]["supplier_order_number"] == "R1"


@pytest.mark.parametrize("response", [{}, {"OrderNumber": None}, True, 12])
def test_supplier_response_without_order_number_stays_unknown(tmp_path, response):
    path = tmp_path / "orders.json"
    router = OrderRouter(live_settings(), Audit(tmp_path / "audit.jsonl"), path)
    with pytest.raises(ValueError):
        router.route({"order_id": "E1"}, lambda _: response)
    assert json.loads(path.read_text())["E1"]["state"] == "UNKNOWN"


def test_cart_names_do_not_collide_after_normalizing_or_truncating():
    from firefinds.fulfillment.randmar_checkout import cart_name_for
    assert cart_name_for("E/1") != cart_name_for("E-1")
    assert cart_name_for("A"*100 + "1") != cart_name_for("A"*100 + "2")
    assert len(cart_name_for("A"*150)) <= 80


def test_preview_uses_exact_mapping_and_checkout_fields():
    from firefinds.fulfillment.preview import prepare_fulfillment
    order = paid_order()
    order["shippingAddress"]["primaryPhone"] = {"phoneNumber": "5550100"}
    c = Candidate("RANDMAR1", D("20"), D("10"), 10, channel_allowed=True)
    args = dict(settings=Settings(), order=order, sku_mapping={order["lineItems"][0]["sku"]: "RANDMAR1"},
                supplier=c, shipping_method_id="GROUND", unit_sale_revenue=D("80"),
                quote_observed_at=1000, now=1050)
    result = prepare_fulfillment(**args)
    assert result.allowed and result.payload["PO"] == order["orderId"]
    assert result.payload["ContactPhone"] == "5550100"
    assert result.payload["AllowPartialShipment"] is False
    assert "5550100" not in json.dumps(result.summary())
    assert "Yonge" not in repr(result)
    for changes, reason in [
        ({"sku_mapping": {}}, "unverified_supplier_mapping"),
        ({"now": 2000}, "stale_or_invalid_supplier_quote"),
        ({"unit_sale_revenue": D("1")}, "sale_below_safe_price"),
        ({"supplier": replace(c, shipping=None)}, "SHIPPING_UNRESOLVED"),
        ({"supplier": replace(c, stock=2)}, "STOCK_BUFFER"),
        ({"supplier": replace(c, channel_allowed=False)}, "CHANNEL_PERMISSION"),
        ({"supplier": replace(c, return_risk=True)}, "RETURN_RISK"),
    ]:
        blocked = prepare_fulfillment(**dict(args, **changes))
        assert not blocked.allowed and blocked.reason == reason


def test_cli_simulation_runs_and_rejects_enabled_gates(monkeypatch, tmp_path, capsys):
    from firefinds.cli.main import main
    import firefinds.cli.sandbox_cmds as commands
    monkeypatch.setattr(commands, "get_settings", lambda: Settings())
    assert main(["simulated-e2e", "--out", str(tmp_path / "simulation")]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["sku_was_in_capacity"] and not report["simulated_fulfillment"]["prepared"]
    monkeypatch.setattr(commands, "get_settings", lambda: Settings(supplier_orders_enabled=True))
    with pytest.raises(ValueError):
        main(["simulated-e2e", "--out", str(tmp_path / "bad")])
    assert not (tmp_path / "bad").exists()


def test_sandbox_command_rejects_production_before_creating_client(monkeypatch, capsys):
    from firefinds.cli.main import main
    import firefinds.cli.sandbox_cmds as commands
    monkeypatch.setattr(commands, "get_settings", lambda: Settings(ebay_env="production"))
    monkeypatch.setattr(commands, "EbayClient", lambda _: pytest.fail("must not touch credentials"))
    assert main(["ebay-sandbox-reads"]) == 2


def test_import_does_not_treat_false_string_as_channel_permission(tmp_path):
    from firefinds.engine.services import RandmarImporter
    c = RandmarImporter(Audit(tmp_path / "a.jsonl")).normalize([
        {"sku": "A", "cost": 10, "shipping": 10, "stock": 10,
         "channel_allowed": "false", "return_risk": False}])[0]
    assert not OpportunityEngine(Settings()).evaluate(c).allowed

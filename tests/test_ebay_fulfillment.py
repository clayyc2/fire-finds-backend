from __future__ import annotations

import pytest

from firefinds.clients.ebay import EbayClient, EbayFulfillmentDisabled
from firefinds.config import Settings


def test_order_reads_use_official_fulfillment_paths(monkeypatch):
    client = EbayClient(Settings())
    calls = []
    monkeypatch.setattr(
        client, "_sell_json",
        lambda method, path, **kwargs: calls.append((method, path, kwargs)) or {},
    )
    client.get_orders(filter_expr="orderfulfillmentstatus:{NOT_STARTED}", limit=25)
    client.get_order("12/34")
    assert calls[0][0] == "GET"
    assert calls[0][1].startswith("/fulfillment/v1/order?")
    assert calls[1][1] == "/fulfillment/v1/order/12%2F34"


def test_store_setup_reads_are_non_mutating(monkeypatch):
    client = EbayClient(Settings(ebay_marketplace_id="EBAY_CA"))
    calls = []
    monkeypatch.setattr(
        client, "_sell_json",
        lambda method, path, **kwargs: calls.append((method, path)) or {},
    )
    client.get_privileges()
    client.get_business_policies()
    client.list_inventory_locations()
    client.get_payments_program()
    client.list_shipping_fulfillments("E/1")
    assert all(method == "GET" for method, _ in calls)
    assert calls[0][1] == "/account/v1/privilege"
    assert any("fulfillment_policy?marketplace_id=EBAY_CA" in path for _, path in calls)
    assert calls[-1][1].endswith("/E%2F1/shipping_fulfillment")


@pytest.mark.parametrize(
    "settings",
    [
        Settings(),
        Settings(dry_run=False, global_kill_switch=True, ebay_tracking_updates_enabled=True),
        Settings(dry_run=False, global_kill_switch=False, ebay_tracking_updates_enabled=False),
    ],
)
def test_tracking_update_fails_closed(settings):
    with pytest.raises(EbayFulfillmentDisabled):
        EbayClient(settings).create_shipping_fulfillment(
            "E1", carrier_code="CanadaPost", tracking_number="T1"
        )


def test_sandbox_tracking_payload_when_explicitly_enabled(monkeypatch):
    client = EbayClient(Settings(
        dry_run=False, global_kill_switch=False,
        ebay_tracking_updates_enabled=True, ebay_env="sandbox",
    ))
    captured = {}
    monkeypatch.setattr(
        client, "_sell_json",
        lambda method, path, **kwargs: captured.update(
            method=method, path=path, **kwargs
        ) or {"fulfillmentId": "F1"},
    )
    result = client.create_shipping_fulfillment(
        "E/1", carrier_code="CanadaPost", tracking_number="TRACK",
        line_items=[{"lineItemId": "L1", "quantity": 1}],
    )
    assert result["fulfillmentId"] == "F1"
    assert captured["path"].endswith("/E%2F1/shipping_fulfillment")
    assert captured["body"]["trackingNumber"] == "TRACK"

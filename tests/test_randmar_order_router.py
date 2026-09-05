from pathlib import Path
import pytest

from firefinds.clients.randmar import RandmarClient, SupplierOrdersDisabled
from firefinds.config import Settings


@pytest.mark.parametrize("settings", [
    Settings(supplier_orders_enabled=False),
    Settings(supplier_orders_enabled=True, dry_run=True, global_kill_switch=False),
    Settings(supplier_orders_enabled=True, dry_run=False, global_kill_switch=True),
])
def test_process_cart_fails_closed(settings):
    with pytest.raises(SupplierOrdersDisabled):
        RandmarClient(settings).process_cart("cart", {"approved": True})


def test_process_cart_uses_supported_boundary(monkeypatch):
    settings = Settings(
        supplier_orders_enabled=True, dry_run=False, global_kill_switch=False
    )
    client = RandmarClient(settings)
    captured = {}
    def fake(method, url, **kwargs):
        captured.update(method=method, url=url, **kwargs)
        return {"OrderNumber": "R-1"}
    monkeypatch.setattr(client, "_request_json", fake)
    result = client.process_cart("ebay-123", {"PurchaseOrder": "123"})
    assert result["OrderNumber"] == "R-1"
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/Cart/ProcessNew/ebay-123")


def test_get_order_is_read_only(monkeypatch):
    client = RandmarClient(Settings())
    captured = {}
    monkeypatch.setattr(client, "_request_json", lambda method, url, **kw: captured.update(method=method, url=url) or {})
    client.get_order("R/1")
    assert captured["method"] == "GET" and captured["url"].endswith("/Order/R%2F1")


def test_order_reads(monkeypatch):
    client = RandmarClient(Settings())
    calls = []
    monkeypatch.setattr(client, "_request_json", lambda method, url, **kw: calls.append((method, url)) or {})
    client.get_order_by_po("EB/1")
    client.list_shipments()
    assert calls[0][1].endswith("/Order/PONumber/EB%2F1")
    assert calls[1][1].endswith("/Orders/Shipments")

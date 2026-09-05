import io
import json
from pathlib import Path
import urllib.error

import pytest

from firefinds.clients.ebay import EbayClient, EbayApiError
from firefinds.config import Settings
from firefinds.engine.order_ingest import OrderIngest
from firefinds.engine.order_poll import poll_orders
from firefinds.engine.services import Audit


def order(oid):
    raw = json.loads((Path(__file__).parent / "fixtures/ebay_paid_order.json").read_text())
    raw["orderId"] = oid
    raw["lineItems"][0]["sku"] = "MERCHANT"
    return raw


def poll_args(tmp_path):
    return dict(ingest=OrderIngest(Settings(), Audit(tmp_path / "audit.jsonl"), tmp_path / "orders.json"),
                sku_mapping={"MERCHANT": "RANDMAR"}, progress_path=tmp_path / "progress.json", page_size=1)


def test_paginated_poll_and_restart_preserve_mapping_and_replay(tmp_path):
    class Client:
        def get_orders(self, *, limit, offset):
            return {"orders": [order(str(offset))], "total": 2}
    args = poll_args(tmp_path)
    first = poll_orders(client=Client(), **args)
    assert first["complete"] and first["orders"] == 2 and first["pages"] == 2
    second = poll_orders(client=Client(), **args)
    assert second["complete"] and not second["submitted"]
    stored = json.loads((tmp_path / "orders.json").read_text())
    assert len(stored) == 2
    assert all(row["sku"] == "RANDMAR" for row in stored.values())
    assert "Yonge" not in (tmp_path / "audit.jsonl").read_text()


def test_poll_failure_keeps_completed_orders_and_does_not_report_success(tmp_path):
    class Client:
        def get_orders(self, *, limit, offset):
            if offset:
                raise TimeoutError("read failed")
            return {"orders": [order("1")], "total": 2}
    with pytest.raises(TimeoutError):
        poll_orders(client=Client(), **poll_args(tmp_path))
    assert "1" in json.loads((tmp_path / "orders.json").read_text())
    progress = json.loads((tmp_path / "progress.json").read_text())
    assert not progress["complete"] and progress["failed_offset"] == 1


def test_poll_rejects_unknown_sku_and_page_budget_is_incomplete(tmp_path):
    class Client:
        def get_orders(self, **kwargs):
            return {"orders": [order("1")], "total": 2}
    args = poll_args(tmp_path)
    args["sku_mapping"] = {}
    result = poll_orders(client=Client(), max_pages=1, **args)
    assert result["blocked"] == 1
    assert not result["complete"] and result["reason"] == "page_budget_reached"


def test_repeated_api_page_is_not_an_endless_loop(tmp_path):
    class Client:
        def get_orders(self, **kwargs):
            return {"orders": [order("1")], "total": 3}
    with pytest.raises(ValueError, match="repeated"):
        poll_orders(client=Client(), **poll_args(tmp_path))


class Response:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self): return b'{"orders": []}'


@pytest.mark.parametrize("method,status,after,expected_calls", [
    ("GET", 429, "2", 2), ("GET", 503, None, 2),
    ("POST", 503, None, 1), ("POST", 429, "2", 1),
    ("GET", 429, "120", 1), ("GET", 403, None, 1),
])
def test_only_reads_retry_and_retry_after_is_respected(monkeypatch, method, status, after, expected_calls):
    client = EbayClient(Settings())
    monkeypatch.setattr(client, "_user_auth_headers", lambda: {})
    calls, sleeps = [], []
    def request(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise urllib.error.HTTPError("https://api.sandbox.ebay.com", status, "error",
                                         {"Retry-After": after} if after else {}, io.BytesIO(b"{}"))
        return Response()
    monkeypatch.setattr("urllib.request.urlopen", request)
    monkeypatch.setattr("time.sleep", sleeps.append)
    if expected_calls == 1:
        with pytest.raises(EbayApiError):
            client._sell_json(method, "/fulfillment/v1/order")
    else:
        assert client._sell_json(method, "/fulfillment/v1/order") == {"orders": []}
        assert sleeps == ([2.0] if after else [1.0])
    assert len(calls) == expected_calls

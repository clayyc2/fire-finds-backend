import json
from types import SimpleNamespace

from firefinds.fulfillment.sweep import sweep_orders


def test_all_discovered_orders_are_refreshed_by_worker(tmp_path):
    seen = []
    def handle(oid):
        seen.append(oid)
        return {"order_id": oid, "state": "HELD", "reason": "needs_verified_quote"}
    ebay = SimpleNamespace(get_orders=lambda **kw: {"orders": [{"orderId": "A"}], "total": 1})
    result = sweep_orders(ebay=ebay, worker=SimpleNamespace(run_order=handle), report_path=tmp_path / "scan.json")
    assert seen == ["A"] and result["complete"] and result["needs_attention"] == 1
    assert json.loads((tmp_path / "scan.json").read_text()) == result


def test_repeated_or_failed_pages_are_incomplete(tmp_path):
    ebay = SimpleNamespace(get_orders=lambda **kw: {"orders": [{"orderId": "A"}], "total": 100})
    worker = SimpleNamespace(run_order=lambda oid: {"state": "HELD"})
    report = sweep_orders(ebay=ebay, worker=worker, report_path=tmp_path / "scan.json", page_size=1)
    assert not report["complete"] and report["orders_checked"] == 1
    ebay.get_orders = lambda **kw: None
    report = sweep_orders(ebay=ebay, worker=worker, report_path=tmp_path / "scan.json")
    assert not report["complete"] and report["error"] == "ValueError"

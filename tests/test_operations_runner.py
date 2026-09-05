from types import SimpleNamespace
import json

from firefinds.config import Settings
from firefinds.ops.runner import run_cycle


def rig(tmp_path):
    ebay = SimpleNamespace(get_orders=lambda **kw: {"orders": [], "total": 0})
    worker = SimpleNamespace(run_order=lambda oid: {"order_id": oid, "state": "HELD", "reason": "not_enabled"})
    supplier = SimpleNamespace(get_products_json=lambda: [{"RandmarSKU": "R1", "Price": 10, "MAP": 0,
        "UnitWeight": 1, "State": "Active", "OpportunityOnly": False, "AvailableQuantity": 20,
        "Title": "Ink", "ProductType": "Inkjet"}])
    return dict(ebay=ebay, supplier=supplier, worker=worker, settings=Settings(), mapping={}, root=tmp_path, clock=lambda: 1000)


def test_cycle_prices_and_persists_status_without_commerce(tmp_path):
    args = rig(tmp_path)
    result = run_cycle(**args)
    assert result["priced_candidates"] == 1 and result["order_sweep_complete"]
    assert not result["automatic_purchases_enabled"] and not result["publishing_enabled"]
    assert not result["needs_attention"]
    assert json.loads((tmp_path / "status.json").read_text()) == result
    assert (tmp_path / "status.json").stat().st_mode & 0o077 == 0
    args["supplier"].get_products_json = lambda: (_ for _ in ()).throw(AssertionError("cached"))
    assert not run_cycle(**args)["errors"]


def test_orders_still_checked_when_catalogue_fails(tmp_path):
    args = rig(tmp_path)
    args["supplier"].get_products_json = lambda: None
    args["ebay"].get_orders = lambda **kw: {"orders": [{"orderId": "A"}], "total": 1}
    result = run_cycle(**args)
    assert result["orders_checked"] == 1 and result["orders_needing_attention"] == 1
    assert result["needs_attention"] and result["errors"] == ["prices:ValueError"]


def test_pricing_survives_failed_order_sweep(tmp_path):
    args = rig(tmp_path)
    args["ebay"].get_orders = lambda **kw: None
    result = run_cycle(**args)
    assert result["priced_candidates"] == 1
    assert result["needs_attention"] and not result["order_sweep_complete"]

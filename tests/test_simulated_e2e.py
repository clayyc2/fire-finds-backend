from pathlib import Path
from firefinds.config import Settings
from firefinds.engine.simulated_e2e import run_simulated_e2e

FIX = Path(__file__).resolve().parent / "fixtures"

def test_simulated_e2e_never_writes(tmp_path):
    settings = Settings()
    assert settings.supplier_orders_enabled is False
    report = run_simulated_e2e(
        settings=settings,
        catalog_path=FIX / "randmar_catalog_mini.json",
        privilege_path=FIX / "ebay_privilege.json",
        order_path=FIX / "ebay_paid_order.json",
        out_dir=tmp_path,
    )
    assert report["state"] == "ROUTED_OFF"
    assert report["process_called"] is False
    assert report["tracking_posted"] is False
    assert report["publish_called"] is False
    assert report["live_sandbox_gets"] == "pending"
    assert report["capacity_item_cap"] == 25
    assert report["sku"] == "0ZD3500TRC638MEF8GM5"
    assert report["sku_was_in_capacity"] is True
    assert "UNSAFE-LOW-STOCK" not in report["selected_skus"]
    assert all(v is False for v in report["gates"].values())

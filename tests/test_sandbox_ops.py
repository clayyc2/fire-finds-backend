import json
from pathlib import Path

from firefinds.config import Settings
from firefinds.engine.capacity_live import parse_privilege_payload
from firefinds.engine.sandbox_ops import fixture_lifecycle, persist_privilege


def test_persist_privilege_does_not_guess(tmp_path):
    snap = parse_privilege_payload({})
    path = persist_privilege(snap, tmp_path / "capacity_live.json")
    body = json.loads(path.read_text())
    assert body["guessed"] is False
    assert body["has_live_cap"] is False
    assert body["quantity"] is None


def test_fixture_lifecycle_routed_off(tmp_path):
    fixture = Path(__file__).resolve().parent / "fixtures" / "ebay_paid_order.json"
    report = fixture_lifecycle(Settings(), fixture, tmp_path)
    assert report["state"] == "ROUTED_OFF"
    assert report["process_called"] is False
    assert report["sku"] == "0ZD3500TRC638MEF8GM5"
    assert (tmp_path / "lifecycle_report.json").is_file()

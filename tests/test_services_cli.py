"""Ingest-stub / ingest-live / score / rank / CLI order gate."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from firefinds.cli.main import main
from firefinds.config import Settings
from firefinds.services import ingest_live, ingest_stub, rank_candidates, score_all


def test_ingest_score_rank_flow(settings: Settings):
    n = ingest_stub(settings)
    assert n == 5
    updated = score_all(settings)
    assert updated == 5
    top = rank_candidates(10, settings=settings)
    assert len(top) >= 1
    for row in top:
        assert row["score"] > 0
    skus = {r["sku"] for r in top}
    assert "FF-STUB-001" in skus
    assert "FF-STUB-004" in skus
    assert "FF-STUB-002" not in skus
    assert "FF-STUB-003" not in skus
    assert "FF-STUB-005" not in skus
    assert settings.actions_jsonl.is_file()


def test_ingest_live_with_mock_client(settings: Settings, tmp_path: Path):
    client = MagicMock()
    client.get_products_json.return_value = [
        {
            "RandmarSKU": "LIVE-001",
            "UPC": "1",
            "MPN": "M1",
            "ManufacturerName": "Acme",
            "MAP": 100.0,
            "MSRP": 110.0,
            "Price": 50.0,
            "AvailableQuantity": 10,
            "Title": "Live item",
        },
        {
            "RandmarSKU": "LIVE-002",
            "MAP": 20.0,
            "MSRP": 25.0,
            "Price": 18.0,
            "AvailableQuantity": 1,
            "ManufacturerName": "Acme",
        },
    ]
    client.get_instant_rebates.return_value = [
        {
            "RandmarSKU": "LIVE-001",
            "InstantRebate": {"RebateAmount": 5.0},
        }
    ]
    count = ingest_live(settings=settings, client=client)
    assert count == 2
    client.get_products_json.assert_called_once()
    client.get_instant_rebates.assert_called_once()
    top = rank_candidates(10, settings=settings)
    skus = {r["sku"] for r in top}
    assert "LIVE-001" in skus
    assert "LIVE-002" not in skus


def test_cli_place_order_refuses(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.setenv("SUPPLIER_ORDERS_ENABLED", "false")
    monkeypatch.setenv("FIREFINDS_DB_PATH", str(tmp_path / "cli.db"))
    monkeypatch.setenv("FIREFINDS_ACTIONS_JSONL", str(tmp_path / "a.jsonl"))
    rc = main(["place-order"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "SUPPLIER_ORDERS_ENABLED is false" in err


def test_cli_ingest_stub(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("FIREFINDS_DB_PATH", str(tmp_path / "cli.db"))
    monkeypatch.setenv("FIREFINDS_ACTIONS_JSONL", str(tmp_path / "a.jsonl"))
    monkeypatch.setenv("SUPPLIER_ORDERS_ENABLED", "false")
    rc = main(["ingest-stub"])
    assert rc == 0
    rc = main(["score"])
    assert rc == 0
    rc = main(["rank", "-n", "3"])
    assert rc == 0

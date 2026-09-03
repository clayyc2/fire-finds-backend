"""Randmar client: credentials, mocked HTTP, order gate."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from firefinds.clients.randmar import (
    RandmarClient,
    SupplierOrdersDisabled,
    extract_rebate_amount,
    normalize_randmar_product,
)
from firefinds.config import Settings


def test_credentials_absent_by_default(settings: Settings):
    client = RandmarClient(settings)
    assert client.credentials_present() is False


def test_credentials_from_secret_file(settings: Settings, tmp_path: Path):
    secrets = tmp_path / "secrets"
    secrets.mkdir(mode=0o700)
    secret_file = secrets / "randmar_api_key.txt"
    secret_file.write_text("dummy-secret\n", encoding="utf-8")
    settings2 = Settings(
        secrets_dir=secrets,
        db_path=settings.db_path,
        actions_jsonl=settings.actions_jsonl,
        supplier_orders_enabled=False,
        randmar_client_id="Fire Finds catalog read",
        randmar_client_secret_file=secret_file,
    )
    client = RandmarClient(settings2)
    assert client.credentials_present() is True
    assert "dummy-secret" not in repr(client)


def test_credentials_from_legacy_secret_names(settings: Settings, tmp_path: Path):
    secrets = tmp_path / "secrets"
    secrets.mkdir(mode=0o700)
    (secrets / "client_id").write_text("dummy-id\n", encoding="utf-8")
    (secrets / "client_secret").write_text("dummy-secret\n", encoding="utf-8")
    settings2 = Settings(
        secrets_dir=secrets,
        db_path=settings.db_path,
        actions_jsonl=settings.actions_jsonl,
        supplier_orders_enabled=False,
        randmar_client_id=None,
        randmar_client_secret_file=None,
    )
    client = RandmarClient(settings2)
    assert client.credentials_present() is True


def test_place_order_refuses_when_gate_off(settings: Settings):
    assert settings.supplier_orders_enabled is False
    client = RandmarClient(settings)
    with pytest.raises(SupplierOrdersDisabled):
        client.place_order(sku="X", qty=1)
    with pytest.raises(SupplierOrdersDisabled):
        client.create_supplier_order(sku="X", qty=1)


def test_place_order_not_implemented_when_gate_on(tmp_path: Path):
    settings = Settings(
        db_path=tmp_path / "t.db",
        actions_jsonl=tmp_path / "a.jsonl",
        secrets_dir=tmp_path / "secrets",
        supplier_orders_enabled=True,
    )
    client = RandmarClient(settings)
    with pytest.raises(NotImplementedError):
        client.place_order(sku="X", qty=1)


def test_fetch_token_without_credentials(settings: Settings):
    client = RandmarClient(settings)
    with pytest.raises(RuntimeError, match="credentials not found"):
        client.fetch_token()


def _mock_urlopen_json(payload: dict | list, status: int = 200):
    resp = MagicMock()
    resp.read.return_value = json.dumps(payload).encode("utf-8")
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


def test_fetch_token_mocked(settings: Settings, tmp_path: Path):
    secrets = tmp_path / "secrets"
    secrets.mkdir(mode=0o700)
    secret_file = secrets / "randmar_api_key.txt"
    secret_file.write_text("dummy-secret", encoding="utf-8")
    settings2 = Settings(
        secrets_dir=secrets,
        db_path=settings.db_path,
        actions_jsonl=settings.actions_jsonl,
        randmar_client_id="Fire Finds catalog read",
        randmar_client_secret_file=secret_file,
        supplier_orders_enabled=False,
    )
    client = RandmarClient(settings2)
    with patch("urllib.request.urlopen") as urlopen:
        urlopen.return_value = _mock_urlopen_json(
            {"access_token": "tok-abc", "expires_in": 3600}
        )
        token = client.fetch_token()
    assert token == "tok-abc"
    # Ensure secret not in request repr accidentally logged via exception paths
    assert "dummy-secret" not in repr(client)
    req = urlopen.call_args[0][0]
    assert req.full_url == settings2.randmar_token_url
    assert req.get_method() == "POST"


def test_get_products_json_post_mocked(settings: Settings, tmp_path: Path):
    secrets = tmp_path / "secrets"
    secrets.mkdir(mode=0o700)
    secret_file = secrets / "randmar_api_key.txt"
    secret_file.write_text("dummy-secret", encoding="utf-8")
    settings2 = Settings(
        secrets_dir=secrets,
        db_path=settings.db_path,
        actions_jsonl=settings.actions_jsonl,
        randmar_client_id="Fire Finds catalog read",
        randmar_client_secret_file=secret_file,
        randmar_reseller_id="2WQN9V11G",
        randmar_api_base="https://api.randmar.io",
        supplier_orders_enabled=False,
    )
    client = RandmarClient(settings2)
    client._access_token = "tok-abc"
    products = [{"RandmarSKU": "SKU1", "MAP": 10.0, "Price": 5.0}]
    with patch("urllib.request.urlopen") as urlopen:
        urlopen.return_value = _mock_urlopen_json(products)
        result = client.get_products_json(manufacturer_id="1825")
    assert result == products
    req = urlopen.call_args[0][0]
    assert req.get_method() == "POST"
    assert "/V4/Reseller/2WQN9V11G/Report/Products/JSON" in req.full_url
    assert "manufacturerId=1825" in req.full_url
    assert req.get_header("Authorization") == "Bearer tok-abc"


def test_get_instant_rebates_get_mocked(settings: Settings, tmp_path: Path):
    settings2 = Settings(
        secrets_dir=tmp_path / "secrets",
        db_path=settings.db_path,
        actions_jsonl=settings.actions_jsonl,
        randmar_reseller_id="2WQN9V11G",
        supplier_orders_enabled=False,
    )
    client = RandmarClient(settings2)
    client._access_token = "tok-abc"
    payload = [
        {
            "RandmarSKU": "SKU1",
            "InstantRebate": {"RebateAmount": 15.0, "PromotionId": "x"},
        }
    ]
    with patch("urllib.request.urlopen") as urlopen:
        urlopen.return_value = _mock_urlopen_json(payload)
        result = client.get_instant_rebates()
    assert result == payload
    req = urlopen.call_args[0][0]
    assert req.get_method() == "GET"
    assert "/V4/Reseller/2WQN9V11G/Products/InstantRebates" in req.full_url


def test_extract_rebate_amount_dict_and_number():
    assert extract_rebate_amount({"RebateAmount": 15.0}) == 15.0
    assert extract_rebate_amount(8) == 8.0
    assert extract_rebate_amount(None) == 0.0
    assert extract_rebate_amount({"RebateAmount": None}) == 0.0


def test_normalize_randmar_product():
    raw = {
        "RandmarSKU": "CN0628C002",
        "UPC": "013803257823",
        "MPN": "0628C002",
        "ManufacturerName": "Canon",
        "MAP": 19.99,
        "MSRP": 23.062,
        "Price": 17.74,
        "AvailableQuantity": 26,
        "Title": "MC-20",
    }
    norm = normalize_randmar_product(raw, rebate=2.5)
    assert norm["sku"] == "CN0628C002"
    assert abs(norm["map"] - 19.99) < 1e-9
    assert abs(norm["dealer_cost"] - 17.74) < 1e-9
    assert norm["stock"] == 26
    assert abs(norm["rebate"] - 2.5) < 1e-9

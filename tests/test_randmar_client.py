"""Randmar client stub: credentials loading + order gate."""

from __future__ import annotations

from pathlib import Path

import pytest

from firefinds.clients.randmar import RandmarClient, SupplierOrdersDisabled
from firefinds.config import Settings


def test_credentials_absent_by_default(settings: Settings):
    client = RandmarClient(settings)
    assert client.credentials_present() is False


def test_credentials_from_secrets_dir(settings: Settings, tmp_path: Path):
    secrets = tmp_path / "secrets"
    secrets.mkdir(mode=0o700)
    (secrets / "client_id").write_text("dummy-id\n", encoding="utf-8")
    (secrets / "client_secret").write_text("dummy-secret\n", encoding="utf-8")
    settings2 = Settings(
        secrets_dir=secrets,
        db_path=settings.db_path,
        actions_jsonl=settings.actions_jsonl,
        supplier_orders_enabled=False,
    )
    client = RandmarClient(settings2)
    assert client.credentials_present() is True
    # Ensure we never accidentally print secrets in repr of public attrs
    assert "dummy-secret" not in repr(client)


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

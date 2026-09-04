"""Pytest fixtures — isolate DB / JSONL under tmp paths."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from firefinds.config import Settings  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(autouse=True)
def _clear_sensitive_env(monkeypatch: pytest.MonkeyPatch):
    """Keep unit tests free of host .env credentials."""
    for key in (
        "RANDMAR_CLIENT_ID",
        "RANDMAR_CLIENT_SECRET",
        "RANDMAR_CLIENT_SECRET_FILE",
        "RANDMAR_SECRETS_DIR",
        "EBAY_CLIENT_ID",
        "EBAY_CLIENT_SECRET",
        "EBAY_CLIENT_SECRET_FILE",
        "EBAY_RUNAME",
        "EBAY_REDIRECT_URI",
        "EBAY_USER_REFRESH_TOKEN_FILE",
        "LIVE_LISTINGS_ENABLED",
        "SUPPLIER_ORDERS_ENABLED",
        "EBAY_SANDBOX_PUBLISH_ENABLED",
        "EBAY_PRODUCTION_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "test.db",
        actions_jsonl=tmp_path / "actions.jsonl",
        secrets_dir=tmp_path / "secrets",
        randmar_client_id=None,
        randmar_client_secret_file=None,
        ebay_client_id=None,
        ebay_client_secret_file=None,
        supplier_orders_enabled=False,
        live_listings_enabled=False,
        ebay_production_enabled=False,
        ebay_sandbox_publish_enabled=False,
        allow_provisional_listable=True,
        min_contribution_profit_cad=8.0,
        min_contribution_margin=0.12,
        stock_buffer=2,
        ship_quote_enabled=False,
    )


@pytest.fixture
def ebay_browse_fixture() -> dict:
    import json

    return json.loads((FIXTURES / "ebay_browse_search.json").read_text())


@pytest.fixture
def cart_shipping_fixture() -> dict:
    import json

    return json.loads((FIXTURES / "cart_shipping_methods.json").read_text())

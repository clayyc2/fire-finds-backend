"""Pytest fixtures — isolate DB / JSONL under tmp paths."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from firefinds.config import Settings  # noqa: E402


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "test.db",
        actions_jsonl=tmp_path / "actions.jsonl",
        secrets_dir=tmp_path / "secrets",
        supplier_orders_enabled=False,
        live_listings_enabled=False,
        ebay_production_enabled=False,
        min_contribution_profit_cad=8.0,
        min_contribution_margin=0.12,
        stock_buffer=2,
    )

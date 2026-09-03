"""eBay sell gates, drafts, queue validation offline."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from firefinds.cli.main import main
from firefinds.clients.ebay import (
    CompetitionSnapshot,
    EbayClient,
    EbayCredentialsMissing,
    EbayListingsDisabled,
    EbayPublishDisabled,
)
from firefinds.config import Settings
from firefinds.db.schema import init_db
from firefinds.listings.drafts import build_inventory_draft
from firefinds.scoring.shipping import InjectedQuoteProvider
from firefinds.services import ingest_stub
from firefinds.services_queue import health_check, validate_eligible_queue


def test_sell_wrappers_refuse_when_live_off(settings: Settings):
    client = EbayClient(settings)
    try:
        client.create_offer({"sku": "X"})
        assert False, "expected refuse"
    except EbayListingsDisabled:
        pass
    try:
        client.publish_offer("oid")
        assert False, "expected refuse"
    except (EbayListingsDisabled, EbayPublishDisabled):
        pass


def test_publish_refuses_even_if_live_without_sandbox_publish(tmp_path: Path):
    settings = Settings(
        db_path=tmp_path / "t.db",
        actions_jsonl=tmp_path / "a.jsonl",
        secrets_dir=tmp_path / "secrets",
        live_listings_enabled=True,
        ebay_sandbox_publish_enabled=False,
        ebay_env="sandbox",
    )
    client = EbayClient(settings)
    try:
        client.publish_offer("oid")
        assert False
    except EbayPublishDisabled:
        pass


def test_require_credentials_message(settings: Settings):
    client = EbayClient(settings)
    try:
        client.require_credentials()
        assert False
    except EbayCredentialsMissing as exc:
        assert "EBAY_CLIENT_ID" in str(exc)


def test_draft_price_map_floored():
    draft = build_inventory_draft(
        {"sku": "S1", "map": 100, "sell_comp": 80, "stock": 10, "title": "T"},
        stock_buffer=2,
    )
    assert draft["publish"] is False
    assert draft["offer"]["pricingSummary"]["price"]["value"] == "100.00"
    assert draft["inventory_item"]["availability"]["shipToLocationAvailability"][
        "quantity"
    ] == 8


def test_validate_queue_offline_with_injected_ship_and_fixture(
    settings: Settings, ebay_browse_fixture
):
    ingest_stub(settings)
    # Mark stubs eligible via score_pass already set by ingest
    conn = init_db(settings.db_path)
    # Build fixture snapshots for stub SKUs that should pass
    from firefinds.clients.ebay import EbayClient

    prices = EbayClient._extract_prices(ebay_browse_fixture)
    # Use a rich competition snap
    snap = CompetitionSnapshot(
        query="stub",
        query_type="upc",
        item_count=len(prices[0]),
        lowest_price=min(prices[0]),
        median_price=sorted(prices[0])[len(prices[0]) // 2],
        sample_url=prices[1][0],
    )
    # Inject shipping so final profitability can pass
    provider = InjectedQuoteProvider(default_cost=12.0)
    # Provide competition fixtures for all skus
    rows = conn.execute("SELECT sku FROM products WHERE score_pass=1").fetchall()
    fixtures = {r["sku"]: snap for r in rows}

    # Mock ebay client without credentials
    ebay = MagicMock()
    ebay.require_credentials.side_effect = EbayCredentialsMissing("missing")
    ebay.credentials_present.return_value = False

    out = validate_eligible_queue(
        settings=settings,
        ebay=ebay,
        quote_provider=provider,
        fixture_competition=fixtures,
        dry_run=False,
        write_drafts=True,
        drafts_dir=settings.db_path.parent / "drafts",
    )
    summary = out["summary"]
    assert summary["eligible_loaded"] >= 1
    # At least FF-STUB-001 / 004 should be able to pass with injected ship
    assert summary["listable_pass_count"] >= 1
    assert summary["shipping_unresolved"] == 0 or summary["listable_pass_count"] >= 1
    queue = conn.execute("SELECT COUNT(*) AS n FROM ranked_queue").fetchone()["n"]
    assert queue == summary["listable_pass_count"]
    export = settings.db_path.parent / "ranked_queue.json"
    assert export.is_file()


def test_validate_queue_unresolved_ship_yields_empty_final(
    settings: Settings,
):
    ingest_stub(settings)
    ebay = MagicMock()
    ebay.require_credentials.side_effect = EbayCredentialsMissing("missing")
    out = validate_eligible_queue(
        settings=settings,
        ebay=ebay,
        quote_provider=InjectedQuoteProvider(),  # all unresolved
        dry_run=False,
        write_drafts=False,
    )
    assert out["summary"]["listable_pass_count"] == 0
    assert out["summary"]["shipping_unresolved"] >= 1


def test_health_and_cli(settings: Settings, monkeypatch, tmp_path: Path, capsys):
    ingest_stub(settings)
    report = health_check(settings=settings)
    assert report["gates"]["LIVE_LISTINGS_ENABLED"] is False
    assert report["gates"]["SUPPLIER_ORDERS_ENABLED"] is False
    assert "secrets_present" in report

    monkeypatch.setenv("FIREFINDS_DB_PATH", str(settings.db_path))
    monkeypatch.setenv("FIREFINDS_ACTIONS_JSONL", str(settings.actions_jsonl))
    monkeypatch.setenv("LIVE_LISTINGS_ENABLED", "false")
    monkeypatch.setenv("SUPPLIER_ORDERS_ENABLED", "false")
    monkeypatch.setenv("SHIP_QUOTE_ENABLED", "false")
    rc = main(["health"])
    assert rc == 0
    rc = main(["ebay-sandbox-status"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "live_listings_enabled" in out

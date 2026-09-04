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
    """Without refresh token + LIVE off → inventory/offer refuse; publish refuse."""
    client = EbayClient(settings)
    assert client.user_refresh_token_present() is False
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


def test_validate_queue_flags_expensive_destinations(settings: Settings):
    ingest_stub(settings)
    snap = CompetitionSnapshot(
        query="stub",
        query_type="upc",
        item_count=5,
        lowest_price=100.0,
        median_price=110.0,
        sample_url="https://ebay.ca/itm/1",
    )
    conn = init_db(settings.db_path)
    rows = conn.execute("SELECT sku FROM products WHERE score_pass=1").fetchall()
    fixtures = {r["sku"]: snap for r in rows}
    ebay = MagicMock()
    ebay.require_credentials.side_effect = EbayCredentialsMissing("missing")
    provider = InjectedQuoteProvider(
        dest_costs={
            "calgary": 10.0,
            "vancouver": 12.0,
            "toronto": 15.0,
            "montreal": 20.0,
            "halifax": 80.0,
        }
    )
    out = validate_eligible_queue(
        settings=settings,
        ebay=ebay,
        quote_provider=provider,
        fixture_competition=fixtures,
        dry_run=False,
        write_drafts=False,
    )
    assert out["summary"]["listable_pass_count"] >= 1
    flagged = [
        r
        for r in out["survivors"]
        if int(r.get("fails_expensive_destinations") or 0) == 1
    ]
    assert flagged, "expected at least one SKU flagged for Halifax"
    cities = flagged[0]["failed_expensive_destinations"]
    assert "Halifax" in cities
    row = conn.execute(
        "SELECT ship_p75, fails_expensive_destinations, failed_expensive_destinations "
        "FROM products WHERE sku=?",
        (flagged[0]["sku"],),
    ).fetchone()
    assert row["fails_expensive_destinations"] == 1
    assert row["ship_p75"] is not None


def test_int_flag_preserves_zero_needs_official():
    """Regression: ``int(x or 1)`` turned cleared needs_official=0 into 1."""
    from firefinds.services_queue import _int_flag

    assert _int_flag({"needs_official_ebay_validation": 0}, "needs_official_ebay_validation", default=1) == 0
    assert _int_flag({"needs_official_ebay_validation": False}, "needs_official_ebay_validation", default=1) == 0
    assert _int_flag({"needs_official_ebay_validation": 1}, "needs_official_ebay_validation", default=1) == 1
    assert _int_flag({}, "needs_official_ebay_validation", default=1) == 1
    assert _int_flag({"provisional_public_ebay": 0}, "provisional_public_ebay", default=0) == 0
    # Document the historical bug shape
    assert int(({"needs_official_ebay_validation": 0}.get("needs_official_ebay_validation") or 1)) == 1


def test_official_browse_clears_needs_official_on_ranked_queue(settings: Settings):
    """Official Browse success must persist needs_official=0 / provisional=0."""
    ingest_stub(settings)
    conn = init_db(settings.db_path)
    # Seed provisional flags as if EDF / public scrape left them set
    conn.execute(
        "UPDATE products SET provisional_public_ebay=1, needs_official_ebay_validation=1"
    )
    conn.commit()

    snap = CompetitionSnapshot(
        query="official",
        query_type="upc",
        item_count=5,
        lowest_price=100.0,
        median_price=110.0,
        sample_url="https://ebay.ca/itm/1",
    )
    ebay = MagicMock()
    ebay.require_credentials.return_value = None
    ebay.competition_for_product.return_value = snap

    out = validate_eligible_queue(
        settings=settings,
        ebay=ebay,
        quote_provider=InjectedQuoteProvider(default_cost=12.0),
        dry_run=False,
        write_drafts=False,
    )
    assert out["summary"]["listable_pass_count"] >= 1
    assert ebay.competition_for_product.called

    rows = conn.execute(
        "SELECT sku, provisional_public_ebay, needs_official_ebay_validation "
        "FROM ranked_queue"
    ).fetchall()
    assert rows, "expected ranked_queue survivors"
    for row in rows:
        assert row["provisional_public_ebay"] == 0, row["sku"]
        assert row["needs_official_ebay_validation"] == 0, row["sku"]

    hist = conn.execute(
        "SELECT provisional_public_ebay, needs_official_ebay_validation "
        "FROM ebay_competition ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert hist["provisional_public_ebay"] == 0
    assert hist["needs_official_ebay_validation"] == 0

    prod = conn.execute(
        "SELECT provisional_public_ebay, needs_official_ebay_validation "
        "FROM products WHERE sku=?",
        (rows[0]["sku"],),
    ).fetchone()
    assert prod["provisional_public_ebay"] == 0
    assert prod["needs_official_ebay_validation"] == 0

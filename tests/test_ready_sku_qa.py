"""Unit tests for ready/listable SKU QA rules."""

from __future__ import annotations

import json
from pathlib import Path

from firefinds.config import Settings
from firefinds.db.schema import init_db
from firefinds.ops.ready_sku_qa import (
    RULE_DUPLICATE_LISTING,
    RULE_IMAGE_INTEGRITY,
    RULE_LISTING_DRAFT,
    RULE_MARGIN_FLOOR,
    RULE_SHIPPING_P75,
    RULE_STOCK_BUFFER,
    check_duplicate_listing,
    check_image_integrity,
    check_listing_draft,
    check_margin_floor,
    check_shipping_p75,
    check_stock_buffer,
    run_ready_sku_qa,
)
from firefinds.cli.main import main


def _row(**overrides):
    base = {
        "sku": "SKU1",
        "cohort": "SAFE_NATIONWIDE",
        "shipping_status": "RESOLVED",
        "ship_p75": 14.5,
        "ship_est": 14.5,
        "map": 100.0,
        "sell_comp": 110.0,
        "opportunity_only": 0,
        "stock": 10,
        "listable_profit": 20.0,
        "listable_margin": 0.2,
        "image_count": 2,
        "image_urls": json.dumps(
            [{"url": "https://api.randmar.io/Product/SKU1/Image/abc"}]
        ),
        "upc_norm": "036000291452",
        "mpn_norm": "ABC",
        "manufacturer": "Acme",
    }
    base.update(overrides)
    return base


def test_shipping_rejects_flat_10(settings: Settings):
    assert check_shipping_p75(_row(ship_p75=10.0)) is not None
    assert check_shipping_p75(_row(ship_p75=10.0)).rule == RULE_SHIPPING_P75
    assert check_shipping_p75(_row(shipping_status="UNRESOLVED")) is not None
    assert check_shipping_p75(_row()) is None


def test_stock_and_margin_floors(settings: Settings):
    assert check_stock_buffer(_row(stock=2), settings).rule == RULE_STOCK_BUFFER
    assert check_stock_buffer(_row(stock=3), settings) is None
    assert (
        check_margin_floor(_row(listable_profit=7.5, listable_margin=0.2), settings).rule
        == RULE_MARGIN_FLOOR
    )
    assert (
        check_margin_floor(_row(listable_profit=20, listable_margin=0.10), settings).rule
        == RULE_MARGIN_FLOOR
    )
    assert check_margin_floor(_row(), settings) is None


def test_image_integrity_safe_only():
    assert check_image_integrity(_row(image_count=0, image_urls=None)).rule == (
        RULE_IMAGE_INTEGRITY
    )
    assert check_image_integrity(_row()) is None
    # DESTINATION_SENSITIVE not required
    assert (
        check_image_integrity(
            _row(cohort="DESTINATION_SENSITIVE", image_count=0, image_urls=None)
        )
        is None
    )


def test_duplicate_listing_upc():
    by_upc = {"036000291452": ["SKU1", "SKU2"]}
    by_mpn = {}
    hit = check_duplicate_listing(_row(), by_upc=by_upc, by_mpn=by_mpn)
    assert hit is not None and hit.rule == RULE_DUPLICATE_LISTING
    assert check_duplicate_listing(
        _row(), by_upc={"036000291452": ["SKU1"]}, by_mpn={}
    ) is None


def test_listing_draft_required_fields(settings: Settings, tmp_path: Path):
    data_dir = tmp_path / "data"
    drafts = data_dir / "listing_drafts"
    drafts.mkdir(parents=True)
    # missing
    assert check_listing_draft(_row(), data_dir=data_dir).rule == RULE_LISTING_DRAFT
    # present but incomplete
    (drafts / "SKU1.json").write_text(json.dumps({"draft": True, "publish": False}))
    assert check_listing_draft(_row(), data_dir=data_dir).rule == RULE_LISTING_DRAFT
    # valid
    (drafts / "SKU1.json").write_text(
        json.dumps(
            {
                "draft": True,
                "publish": False,
                "inventory_item": {
                    "sku": "SKU1",
                    "product": {"title": "Widget"},
                    "availability": {
                        "shipToLocationAvailability": {"quantity": 5}
                    },
                },
                "offer": {
                    "availableQuantity": 5,
                    "pricingSummary": {
                        "price": {"value": "100.00", "currency": "CAD"}
                    },
                },
            }
        )
    )
    assert check_listing_draft(_row(), data_dir=data_dir) is None


def test_run_ready_sku_qa_writes_reports(settings: Settings, tmp_path: Path):
    # Point settings db under tmp and seed one SAFE listable + draft
    db = tmp_path / "t.db"
    settings = Settings(
        db_path=db,
        actions_jsonl=tmp_path / "a.jsonl",
        secrets_dir=tmp_path / "secrets",
        live_listings_enabled=False,
        supplier_orders_enabled=False,
        ebay_sandbox_publish_enabled=False,
        min_contribution_profit_cad=8.0,
        min_contribution_margin=0.12,
        stock_buffer=2,
    )
    conn = init_db(db)
    conn.execute(
        """
        INSERT INTO products (
          sku, title, manufacturer, upc, upc_norm, mpn, mpn_norm, map, stock,
          sell_comp, listable_profit, listable_margin, shipping_status, ship_p75,
          listable_pass, listable, eligible, score_pass, cohort, pipeline_source,
          opportunity_only, image_count, image_urls
        ) VALUES (
          'OK1', 'T', 'Acme', '036000291452', '036000291452', 'M1', 'M1', 50, 9,
          60, 15.0, 0.2, 'RESOLVED', 12.5,
          1, 1, 1, 1, 'SAFE_NATIONWIDE', 'RANDMAR_FIRST',
          0, 1, ?
        )
        """,
        (json.dumps([{"url": "https://example.com/a.jpg"}]),),
    )
    conn.execute(
        """
        INSERT INTO products (
          sku, title, manufacturer, map, stock,
          sell_comp, listable_profit, listable_margin, shipping_status, ship_p75,
          listable_pass, listable, eligible, score_pass, cohort, pipeline_source,
          opportunity_only, image_count
        ) VALUES (
          'BAD1', 'T2', 'Acme', 50, 1,
          60, 5.0, 0.05, 'UNRESOLVED', 10.0,
          1, 1, 1, 1, 'SAFE_NATIONWIDE', 'RANDMAR_FIRST',
          0, 0
        )
        """
    )
    conn.commit()
    data_dir = tmp_path
    # settings.db_path.parent is tmp_path; put drafts there
    ddir = data_dir / "listing_drafts"
    ddir.mkdir()
    for sku in ("OK1", "BAD1"):
        (ddir / f"{sku}.json").write_text(
            json.dumps(
                {
                    "draft": True,
                    "publish": False,
                    "inventory_item": {
                        "sku": sku,
                        "product": {"title": "T"},
                        "availability": {
                            "shipToLocationAvailability": {"quantity": 1}
                        },
                    },
                    "offer": {
                        "availableQuantity": 1,
                        "pricingSummary": {
                            "price": {"value": "50.00", "currency": "CAD"}
                        },
                    },
                }
            )
        )
    # reports dir under db parent
    report = run_ready_sku_qa(settings=settings, write_reports=True, top_n=10)
    assert report["universe_count"] == 2
    assert report["skus_failing"] >= 1
    assert report["fail_counts_by_rule"][RULE_SHIPPING_P75] >= 1
    assert (tmp_path / "reports" / "ready_sku_qa_latest.json").is_file()
    assert (tmp_path / "reports" / "ready_sku_qa_latest.md").is_file()
    conn.close()


def test_cli_qa_ready_help():
    try:
        main(["qa-ready", "--help"])
    except SystemExit as exc:
        assert exc.code == 0

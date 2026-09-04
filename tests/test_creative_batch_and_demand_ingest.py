"""Batch creative drafts + EBAY_DEMAND_FIRST provisional ingest CLI."""

from __future__ import annotations

import json
from pathlib import Path

from firefinds.cli.main import main
from firefinds.config import Settings
from firefinds.db.schema import init_db
from firefinds.discovery.ebay_demand import (
    load_demand_signals_from_json,
    ingest_provisional_demand_matches,
)
from firefinds.listings.creative_batch import (
    batch_write_creative_drafts,
    optimize_draft_fields,
)
from firefinds.pipelines.cohorts import split_randmar_cohorts
from firefinds.sku_record.constants import (
    CREATIVE_AI_ENHANCED,
    CREATIVE_ORIGINAL_SUPPLIER,
    PIPELINE_EBAY_DEMAND_FIRST,
)
from firefinds.services import ingest_stub


def _seed_ranked(settings: Settings) -> tuple[str, str]:
    ingest_stub(settings)
    conn = init_db(settings.db_path)
    rows = conn.execute(
        "SELECT sku, map, stock FROM products WHERE score_pass=1 ORDER BY sku"
    ).fetchall()
    assert len(rows) >= 2
    conn.execute("DELETE FROM ranked_queue")
    conn.execute(
        """
        INSERT INTO ranked_queue (
            rank, sku, rank_score, expected_monthly_contribution_profit,
            sales_probability, sell_comp, listable_profit, listable_margin,
            map, stock, provisional_public_ebay, needs_official_ebay_validation,
            reason, ship_p75, shipping_status, fails_expensive_destinations,
            failed_expensive_destinations
        ) VALUES (1, ?, 10, 50, 0.5, ?, 40, 0.2, ?, ?, 1, 1, 'ok', 12.0,
                  'RESOLVED', 0, '[]')
        """,
        (rows[0]["sku"], float(rows[0]["map"] or 100), float(rows[0]["map"] or 100), rows[0]["stock"]),
    )
    conn.execute(
        """
        INSERT INTO ranked_queue (
            rank, sku, rank_score, expected_monthly_contribution_profit,
            sales_probability, sell_comp, listable_profit, listable_margin,
            map, stock, provisional_public_ebay, needs_official_ebay_validation,
            reason, ship_p75, shipping_status, fails_expensive_destinations,
            failed_expensive_destinations
        ) VALUES (2, ?, 8, 40, 0.4, ?, 30, 0.18, ?, ?, 1, 1, 'ok', 25.0,
                  'RESOLVED', 1, '["Halifax"]')
        """,
        (rows[1]["sku"], float(rows[1]["map"] or 100), float(rows[1]["map"] or 100), rows[1]["stock"]),
    )
    conn.execute(
        "UPDATE products SET shipping_status='RESOLVED', listable_pass=1, "
        "fails_expensive_destinations=0, manufacturer=IFNULL(manufacturer,'Acme'), "
        "mpn=IFNULL(mpn,'MPN-SAFE'), title=IFNULL(title,'Acme MPN-SAFE') WHERE sku=?",
        (rows[0]["sku"],),
    )
    conn.execute(
        "UPDATE products SET shipping_status='RESOLVED', listable_pass=1, "
        "fails_expensive_destinations=1 WHERE sku=?",
        (rows[1]["sku"],),
    )
    # quarantine seed
    conn.execute(
        """
        INSERT OR IGNORE INTO products (sku, map, msrp, dealer_cost, stock, score_pass,
                              eligible, shipping_status, listable_pass)
        VALUES ('FF-UNRES-BATCH', 50, 60, 20, 10, 0, 0, 'UNRESOLVED', 0)
        """
    )
    conn.execute(
        "UPDATE products SET shipping_status='UNRESOLVED' WHERE sku='FF-UNRES-BATCH'"
    )
    conn.commit()
    conn.close()
    return rows[0]["sku"], rows[1]["sku"]


def test_optimize_draft_fields_variants():
    product = {
        "sku": "X1",
        "title": "Widget",
        "manufacturer": "Acme",
        "mpn": "W-1",
        "upc": "012345678905",
        "map": 100,
        "sell_comp": 100,
        "stock": 10,
        "category": "Widgets",
    }
    orig = optimize_draft_fields(product, creative_variant=CREATIVE_ORIGINAL_SUPPLIER)
    assert orig["creative_variant"] == CREATIVE_ORIGINAL_SUPPLIER
    assert orig["publish"] is False
    ai = optimize_draft_fields(product, creative_variant=CREATIVE_AI_ENHANCED)
    assert ai["creative_variant"] == CREATIVE_AI_ENHANCED
    assert "Acme" in ai["inventory_item"]["product"]["title"]
    assert "Brand:" in ai["inventory_item"]["product"]["description"]


def test_batch_creative_writes_separated_dirs(settings: Settings):
    safe_sku, sens_sku = _seed_ranked(settings)
    split = split_randmar_cohorts(settings=settings, snapshot_id="batchsnap")
    assert split["summary"]["safe_nationwide"] == 1
    assert split["summary"]["destination_sensitive"] == 1

    result = batch_write_creative_drafts(
        settings=settings, snapshot_id="batchsnap", include_ai_twin=True
    )
    assert result["summary"]["skus_written"] == 2
    root = Path(result["summary"]["drafts_root"])
    assert (root / "safe_nationwide" / f"{safe_sku}.ORIGINAL_SUPPLIER.json").is_file()
    assert (root / "safe_nationwide" / f"{safe_sku}.AI_ENHANCED.json").is_file()
    assert (root / "destination_sensitive" / f"{sens_sku}.ORIGINAL_SUPPLIER.json").is_file()

    conn = init_db(settings.db_path)
    row = dict(conn.execute("SELECT * FROM products WHERE sku=?", (safe_sku,)).fetchone())
    conn.close()
    assert row.get("creative_variant") == CREATIVE_ORIGINAL_SUPPLIER
    assert row.get("creative_version_id")
    assets = json.loads(row["asset_paths"]) if isinstance(row["asset_paths"], str) else row["asset_paths"]
    assert any("ORIGINAL_SUPPLIER" in a for a in assets)
    assert any("AI_ENHANCED" in a for a in assets)


def test_load_and_ingest_demand_signals(settings: Settings, tmp_path: Path):
    ingest_stub(settings)
    conn = init_db(settings.db_path)
    row = conn.execute(
        "SELECT * FROM products WHERE score_pass=1 ORDER BY sku LIMIT 1"
    ).fetchone()
    assert row is not None
    conn.execute(
        """
        UPDATE products SET shipping_status='RESOLVED', ship_p75=10.0,
               ship_est=10.0, fails_expensive_destinations=0,
               listable_pass=1, net_cost=IFNULL(dealer_cost,0)
        WHERE sku=?
        """,
        (row["sku"],),
    )
    product = dict(
        conn.execute("SELECT * FROM products WHERE sku=?", (row["sku"],)).fetchone()
    )
    conn.commit()
    conn.close()

    signals_path = tmp_path / "provisional_matches.json"
    signals_path.write_text(
        json.dumps(
            {
                "matches": [
                    {
                        "query": str(product.get("upc") or product.get("mpn") or product["sku"]),
                        "query_type": "upc" if product.get("upc") else "mpn",
                        "upc": product.get("upc"),
                        "mpn": product.get("mpn"),
                        "manufacturer": product.get("manufacturer"),
                        "sold_count": 4,
                        "active_count": 2,
                        "repeated_demand": True,
                        "lowest_price": float(product.get("map") or 100),
                        "median_price": float(product.get("map") or 100),
                        "provisional_public_ebay": True,
                        "needs_official_ebay_validation": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    loaded = load_demand_signals_from_json(signals_path)
    assert len(loaded) == 1
    assert loaded[0].provisional_public_ebay is True

    out = ingest_provisional_demand_matches(
        signals_path=signals_path,
        snapshot_id="edfingest",
        settings=settings,
    )
    assert out["summary"]["pipeline_source"] == PIPELINE_EBAY_DEMAND_FIRST
    assert out["summary"]["ingested_signal_count"] == 1
    assert out["summary"]["signals_seen"] == 1


def test_cli_batch_and_ingest(settings: Settings, tmp_path: Path, monkeypatch):
    import firefinds.cli.main as cli_main

    monkeypatch.setattr(cli_main, "get_settings", lambda: settings)

    _seed_ranked(settings)
    assert main(["split-cohorts", "--snapshot-id", "clisnap"]) == 0
    assert main(["batch-creative-drafts", "--snapshot-id", "clisnap", "--limit", "1"]) == 0
    root = Path(settings.db_path).parent / "drafts" / "randmar_first"
    assert list((root / "safe_nationwide").glob("*.ORIGINAL_SUPPLIER.json"))

    # demand ingest empty scaffold file
    empty = tmp_path / "empty_signals.json"
    empty.write_text(json.dumps({"signals": []}), encoding="utf-8")
    assert (
        main(
            [
                "ebay-demand-ingest",
                "--snapshot-id",
                "clisnap",
                "--signals-file",
                str(empty),
            ]
        )
        == 0
    )

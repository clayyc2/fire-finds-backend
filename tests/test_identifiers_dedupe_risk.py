"""UPC/MPN normalize, dedupe, return-risk, MAP floor."""

from __future__ import annotations

from firefinds.scoring.competition import apply_map_floor, resolve_compete_sell_price
from firefinds.clients.ebay import CompetitionSnapshot
from firefinds.scoring.dedupe import dedupe_products
from firefinds.scoring.identifiers import (
    canonicalize_mpn,
    normalize_upc,
    upc_ean_checksum_ok,
)
from firefinds.scoring.return_risk import evaluate_return_risk


def test_upc_checksum_valid():
    # Well-known valid UPC-A check digit example: 036000291452
    assert upc_ean_checksum_ok("036000291452")
    code, ok = normalize_upc("036 000 291 452")
    assert ok and code == "036000291452"


def test_upc_checksum_invalid():
    code, ok = normalize_upc("123456789013")
    assert code == "123456789013"
    assert ok is False


def test_canonicalize_mpn():
    assert canonicalize_mpn(" ab-12 c ") == "AB-12C"


def test_dedupe_keeps_best_stock():
    rows = [
        {"sku": "A", "upc_norm": "1", "stock": 2, "contribution_profit": 50},
        {"sku": "B", "upc_norm": "1", "stock": 9, "contribution_profit": 10},
    ]
    kept, merges = dedupe_products(rows)
    assert len(kept) == 1
    assert kept[0]["sku"] == "B"
    assert len(merges) == 1


def test_return_risk_hazmat():
    r = evaluate_return_risk({"title": "Lithium battery pack", "unit_weight": 1})
    assert r.excluded is True


def test_map_floor():
    sell, below = apply_map_floor(90.0, 100.0)
    assert sell == 100.0 and below is True


def test_compete_sell_never_suggests_below_map_after_floor():
    snap = CompetitionSnapshot(
        query="x", query_type="upc", item_count=3,
        lowest_price=80.0, median_price=85.0, sample_url=None,
    )
    raw = resolve_compete_sell_price(
        {"map": 100.0}, snap, strategy="min_map_median", median_factor=0.98
    )
    # min(100, 85*0.98)=83.3 → below map
    assert raw < 100
    floored, _ = apply_map_floor(raw, 100.0)
    assert floored == 100.0

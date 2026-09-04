"""Randmar product image list + still download + SAFE_NATIONWIDE backfill (mocked)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from firefinds.clients.randmar import RandmarClient
from firefinds.config import Settings
from firefinds.db.schema import init_db
from firefinds.listings.drafts import build_inventory_draft
from firefinds.services_images import (
    WORKING_ENDPOINT,
    backfill_safe_nationwide_images,
    normalize_image_urls,
)


def _mock_urlopen_json(payload: dict | list, status: int = 200):
    resp = MagicMock()
    resp.read.return_value = json.dumps(payload).encode("utf-8")
    resp.headers = {"Content-Type": "application/json"}
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


def _mock_urlopen_bytes(body: bytes, ctype: str = "image/png"):
    resp = MagicMock()
    resp.read.return_value = body
    resp.headers = {"Content-Type": ctype}
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


def test_normalize_image_urls_primary_first():
    rows = normalize_image_urls(
        [
            {"Url": "https://example/b", "IsPrimary": False, "SortOrder": 2},
            {"Url": "https://example/a", "IsPrimary": True, "SortOrder": 9},
            {"Url": "", "IsPrimary": True},
        ]
    )
    assert [r["url"] for r in rows] == ["https://example/a", "https://example/b"]
    assert rows[0]["is_primary"] is True


def test_get_product_images_mocked_public_default(settings: Settings):
    client = RandmarClient(settings)
    payload = [
        {
            "ImageId": "img1",
            "Url": "https://api.randmar.io/Product/SKU1/Image/img1",
            "IsPrimary": True,
            "SortOrder": 0,
        }
    ]
    with patch("urllib.request.urlopen") as urlopen:
        urlopen.return_value = _mock_urlopen_json(payload)
        result = client.get_product_images("SKU1")
    assert result == payload
    req = urlopen.call_args[0][0]
    assert req.get_method() == "GET"
    assert req.full_url.endswith("/Product/SKU1/Images")
    assert "GenerateImage" not in req.full_url
    assert "Authorization" not in req.headers


def test_download_product_image_mocked(settings: Settings):
    client = RandmarClient(settings)
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    with patch("urllib.request.urlopen") as urlopen:
        urlopen.return_value = _mock_urlopen_bytes(png, "image/png")
        body, ctype = client.download_product_image("SKU1", "abc123")
    assert body == png
    assert "png" in ctype
    req = urlopen.call_args[0][0]
    assert req.full_url.endswith("/Product/SKU1/Image/abc123")
    assert req.get_method() == "GET"
    assert "Authorization" not in req.headers


def test_get_manufacturer_product_images_path(settings: Settings):
    client = RandmarClient(settings)
    client._access_token = "tok-abc"
    with patch("urllib.request.urlopen") as urlopen:
        urlopen.return_value = _mock_urlopen_json([])
        client.get_manufacturer_product_images("5001", "SKU1")
    req = urlopen.call_args[0][0]
    assert "/V4/Manufacturer/5001/Product/SKU1/Images" in req.full_url
    assert req.get_method() == "GET"


def test_backfill_safe_nationwide_images_checkpoint(settings: Settings, tmp_path: Path):
    conn = init_db(settings.db_path)
    conn.execute(
        "INSERT INTO products (sku, manufacturer) VALUES (?, ?)",
        ("SAFE1", "Epson"),
    )
    conn.execute(
        """
        INSERT INTO candidate_cohorts (
            sku, pipeline_source, cohort, comparison_cohort_id, snapshot_id, rank
        ) VALUES (?, 'RANDMAR_FIRST', 'SAFE_NATIONWIDE',
                  'snap|RANDMAR_FIRST|SAFE_NATIONWIDE', 'snap', 1)
        """,
        ("SAFE1",),
    )
    conn.commit()
    conn.close()

    client = MagicMock()
    client.credentials_present.return_value = False
    client.get_product_images.return_value = [
        {
            "ImageId": "i1",
            "Url": "https://api.randmar.io/Product/SAFE1/Image/i1",
            "IsPrimary": True,
            "SortOrder": 0,
            "FileName": "i1.png",
            "ContentType": "image/png",
        }
    ]
    client.download_product_image.return_value = (b"\x89PNG" + b"\x00" * 20, "image/png")

    summary = backfill_safe_nationwide_images(
        settings=settings,
        snapshot_id="snap",
        sleep_sec=0.0,
        resume=True,
        client=client,
        download_binaries=True,
        use_token=False,
    )
    assert summary["skus_with_ge1_image_url"] == 1
    assert summary["skus_with_ge1_local_still"] == 1
    assert summary["endpoint"] == WORKING_ENDPOINT
    assert summary["public_noauth"] is True
    assert summary["live_listings_enabled"] is False
    assert summary["supplier_orders_enabled"] is False

    map_path = Path(settings.db_path).parent / "images" / "sku_image_urls.json"
    assert map_path.is_file()
    payload = json.loads(map_path.read_text(encoding="utf-8"))
    assert payload["SAFE1"]["image_count"] == 1
    assert payload["SAFE1"]["local_paths"]

    meta = Path(settings.db_path).parent / "images" / "SAFE1" / "metadata.json"
    assert meta.is_file()
    meta_j = json.loads(meta.read_text(encoding="utf-8"))
    assert meta_j["primary_image_id"] == "i1"
    assert (Path(settings.db_path).parent / "images" / "SAFE1" / "i1.png").is_file()

    conn = init_db(settings.db_path)
    row = conn.execute(
        """
        SELECT image_count, image_urls, supplier_image_urls, supplier_image_local_paths
        FROM products WHERE sku='SAFE1'
        """
    ).fetchone()
    assert int(row["image_count"]) == 1
    assert "api.randmar.io" in (row["image_urls"] or "")
    assert "api.randmar.io" in (row["supplier_image_urls"] or "")
    assert "images/SAFE1/" in (row["supplier_image_local_paths"] or "")
    conn.close()

    # Resume skips already-complete SKU (binaries present)
    client.get_product_images.reset_mock()
    client.download_product_image.reset_mock()
    summary2 = backfill_safe_nationwide_images(
        settings=settings,
        snapshot_id="snap",
        sleep_sec=0.0,
        resume=True,
        client=client,
        download_binaries=True,
        use_token=False,
    )
    assert summary2["skipped_resume"] == 1
    client.get_product_images.assert_not_called()
    client.download_product_image.assert_not_called()


def test_backfill_refuses_when_live_gates_on(tmp_path: Path):
    settings = Settings(
        db_path=tmp_path / "t.db",
        actions_jsonl=tmp_path / "a.jsonl",
        secrets_dir=tmp_path / "secrets",
        live_listings_enabled=True,
        supplier_orders_enabled=False,
    )
    with pytest.raises(RuntimeError, match="LIVE_LISTINGS"):
        backfill_safe_nationwide_images(
            settings=settings, snapshot_id="snap", sleep_sec=0.0
        )


def test_draft_includes_image_urls():
    draft = build_inventory_draft(
        {
            "sku": "S1",
            "title": "Widget",
            "map": 10.0,
            "sell_comp": 12.0,
            "stock": 5,
            "image_urls": [
                {"url": "https://api.randmar.io/Product/S1/Image/a", "is_primary": True}
            ],
        }
    )
    assert draft["inventory_item"]["product"]["imageUrls"] == [
        "https://api.randmar.io/Product/S1/Image/a"
    ]

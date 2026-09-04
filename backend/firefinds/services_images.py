"""Backfill authorized Randmar supplier stills for SAFE_NATIONWIDE SKUs.

Public read-only endpoints (no Integration secret required):
  GET /Product/{sku}/Images
  GET /Product/{sku}/Image/{imageId}

Never GenerateImage / AppendImage / manufacturer upload POSTs.
LIVE_LISTINGS and supplier orders stay OFF.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from firefinds.clients.randmar import RandmarClient
from firefinds.config import Settings, get_settings
from firefinds.db.schema import init_db
from firefinds.pipelines.tags import COHORT_SAFE_NATIONWIDE, PIPELINE_RANDMAR_FIRST

logger = logging.getLogger(__name__)

PROGRESS_NAME = "backfill_progress.json"
URLS_MAP_NAME = "sku_image_urls.json"
SUMMARY_NAME = "backfill_summary.json"
METADATA_NAME = "metadata.json"
WORKING_ENDPOINT = "GET /Product/{randmarSKU}/Images"
IMAGE_ENDPOINT = "GET /Product/{randmarSKU}/Image/{imageId}"

_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def images_dir(settings: Settings) -> Path:
    return Path(settings.db_path).parent / "images"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def _load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def normalize_image_urls(images: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep metadata + absolute URLs; sort primary first then SortOrder."""
    rows: list[dict[str, Any]] = []
    for item in images:
        url = item.get("Url") or item.get("url")
        if not url:
            continue
        rows.append(
            {
                "image_id": item.get("ImageId") or item.get("imageId"),
                "url": str(url),
                "is_primary": bool(item.get("IsPrimary") or item.get("isPrimary")),
                "sort_order": item.get("SortOrder", item.get("sortOrder")),
                "file_name": item.get("FileName") or item.get("fileName"),
                "content_type": item.get("ContentType") or item.get("contentType"),
                "content_length": item.get("ContentLength")
                or item.get("contentLength"),
                "description": item.get("Description") or item.get("description"),
            }
        )

    def _key(row: dict[str, Any]) -> tuple[int, int, str]:
        so = row.get("sort_order")
        try:
            so_i = int(so) if so is not None else 10_000
        except (TypeError, ValueError):
            so_i = 10_000
        return (0 if row.get("is_primary") else 1, so_i, str(row.get("url") or ""))

    rows.sort(key=_key)
    return rows


def list_safe_nationwide_skus(
    conn,
    *,
    snapshot_id: str,
    pipeline_source: str = PIPELINE_RANDMAR_FIRST,
    limit: int | None = None,
) -> list[str]:
    sql = """
        SELECT c.sku
        FROM candidate_cohorts c
        WHERE c.cohort = ?
          AND c.pipeline_source = ?
          AND c.snapshot_id = ?
        ORDER BY IFNULL(c.rank, 999999), c.sku
    """
    params: list[Any] = [COHORT_SAFE_NATIONWIDE, pipeline_source, snapshot_id]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))
    return [str(r[0]) for r in conn.execute(sql, params).fetchall()]


def _ext_for(content_type: str | None, file_name: str | None, image_id: str) -> str:
    if file_name and "." in file_name:
        ext = Path(file_name).suffix.lower()
        if ext and len(ext) <= 8:
            return ext
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ctype:
        guessed = mimetypes.guess_extension(ctype, strict=False)
        if guessed == ".jpe":
            guessed = ".jpg"
        if guessed:
            return guessed
    return ".bin"


def _safe_image_id(image_id: str) -> str:
    cleaned = _SAFE_ID_RE.sub("_", str(image_id or "").strip())
    return cleaned or "image"


def sku_image_dir(out_dir: Path, sku: str) -> Path:
    return out_dir / str(sku)


def metadata_path_for(out_dir: Path, sku: str) -> Path:
    return sku_image_dir(out_dir, sku) / METADATA_NAME


def sku_binaries_complete(out_dir: Path, sku: str, expected_count: int) -> bool:
    meta_path = metadata_path_for(out_dir, sku)
    if not meta_path.is_file():
        return False
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    images = meta.get("images") or []
    if int(meta.get("image_count") or 0) != expected_count:
        return False
    if len(images) != expected_count:
        return False
    for row in images:
        local = row.get("local_path")
        if not local:
            return False
        # local_path stored relative to data/ or absolute under out_dir
        candidates = [
            Path(local),
            out_dir.parent / local,
            out_dir / local,
            Path.cwd() / local,
        ]
        if not any(c.is_file() for c in candidates):
            # also try relative to sku dir via filename
            name = Path(str(local)).name
            if not (sku_image_dir(out_dir, sku) / name).is_file():
                return False
    return True


def persist_sku_image_urls(
    conn,
    sku: str,
    images: list[dict[str, Any]],
) -> None:
    urls_only = [row["url"] for row in images if row.get("url")]
    local_paths = [row["local_path"] for row in images if row.get("local_path")]
    conn.execute(
        """
        UPDATE products
        SET image_urls=?,
            image_count=?,
            images_fetched_at=?,
            supplier_image_urls=?,
            supplier_image_local_paths=?,
            updated_at=datetime('now')
        WHERE sku=?
        """,
        (
            json.dumps(images, default=str),
            len(urls_only),
            _utc_now(),
            json.dumps(urls_only, default=str),
            json.dumps(local_paths, default=str),
            sku,
        ),
    )


def download_sku_stills(
    *,
    rm: RandmarClient,
    sku: str,
    images: list[dict[str, Any]],
    out_dir: Path,
    sleep_sec: float,
    use_token: bool = False,
) -> list[dict[str, Any]]:
    """Download Image/{id} bytes into data/images/{sku}/; return rows with local_path."""
    dest = sku_image_dir(out_dir, sku)
    dest.mkdir(parents=True, exist_ok=True)
    enriched: list[dict[str, Any]] = []
    primary_id = None
    for idx, row in enumerate(images):
        image_id = str(row.get("image_id") or "")
        if not image_id:
            continue
        if idx and sleep_sec > 0:
            time.sleep(sleep_sec)
        safe_id = _safe_image_id(image_id)
        # Prefer existing file if present (resume within SKU)
        existing = list(dest.glob(f"{safe_id}.*"))
        existing = [p for p in existing if p.name != METADATA_NAME and p.is_file()]
        if existing:
            local = existing[0]
            ctype = row.get("content_type")
            body_len = local.stat().st_size
        else:
            body, ctype = rm.download_product_image(
                sku, image_id, use_token=use_token
            )
            ext = _ext_for(ctype, row.get("file_name"), image_id)
            local = dest / f"{safe_id}{ext}"
            tmp = local.with_suffix(local.suffix + ".tmp")
            tmp.write_bytes(body)
            tmp.replace(local)
            body_len = len(body)
        rel = f"images/{sku}/{local.name}"
        entry = {
            **row,
            "content_type": ctype or row.get("content_type"),
            "content_length": body_len,
            "local_path": rel,
            "local_file": local.name,
        }
        enriched.append(entry)
        if entry.get("is_primary"):
            primary_id = image_id

    if primary_id is None and enriched:
        primary_id = enriched[0].get("image_id")

    meta = {
        "sku": sku,
        "endpoint_list": WORKING_ENDPOINT,
        "endpoint_image": IMAGE_ENDPOINT,
        "fetched_at": _utc_now(),
        "image_count": len(enriched),
        "primary_image_id": primary_id,
        "images": enriched,
        "urls": [r["url"] for r in enriched if r.get("url")],
        "local_paths": [r["local_path"] for r in enriched if r.get("local_path")],
    }
    _write_json(dest / METADATA_NAME, meta)
    return enriched


def backfill_safe_nationwide_images(
    *,
    settings: Settings | None = None,
    snapshot_id: str,
    sleep_sec: float | None = None,
    limit: int | None = None,
    resume: bool = True,
    force: bool = False,
    client: RandmarClient | None = None,
    download_binaries: bool = True,
    use_token: bool = False,
) -> dict[str, Any]:
    """Fetch Randmar image URLs (+ optional stills) for SAFE_NATIONWIDE SKUs.

    Checkpoint: data/images/backfill_progress.json
    Map:        data/images/sku_image_urls.json
    Stills:     data/images/{sku}/{imageId}.ext + metadata.json
    Also writes image_urls / supplier_image_* onto products rows.

    Public endpoints by default (use_token=False) — does not read Integration secrets.
    """
    settings = settings or get_settings()
    if settings.live_listings_enabled or settings.supplier_orders_enabled:
        raise RuntimeError(
            "Refusing image backfill while LIVE_LISTINGS or SUPPLIER_ORDERS is ON"
        )

    sleep = (
        float(sleep_sec)
        if sleep_sec is not None
        else float(settings.ship_quote_sleep_sec)
    )
    out_dir = images_dir(settings)
    out_dir.mkdir(parents=True, exist_ok=True)
    progress_path = out_dir / PROGRESS_NAME
    map_path = out_dir / URLS_MAP_NAME

    conn = init_db(settings.db_path)
    skus = list_safe_nationwide_skus(conn, snapshot_id=snapshot_id, limit=limit)
    url_map: dict[str, Any] = _load_json(map_path, {})
    if not isinstance(url_map, dict):
        url_map = {}
    progress: dict[str, Any] = _load_json(
        progress_path,
        {
            "snapshot_id": snapshot_id,
            "endpoint": WORKING_ENDPOINT,
            "image_endpoint": IMAGE_ENDPOINT,
            "completed": {},
            "failed": {},
            "started_at": _utc_now(),
        },
    )
    if not resume or progress.get("snapshot_id") != snapshot_id:
        progress = {
            "snapshot_id": snapshot_id,
            "endpoint": WORKING_ENDPOINT,
            "image_endpoint": IMAGE_ENDPOINT,
            "completed": {},
            "failed": {},
            "started_at": _utc_now(),
        }

    completed: dict[str, Any] = dict(progress.get("completed") or {})
    failed: dict[str, Any] = dict(progress.get("failed") or {})

    rm = client or RandmarClient(settings)
    # Public Product/Images + Image/{id} — no Integration secret required.
    if use_token and not rm.credentials_present():
        raise RuntimeError(
            "Randmar credentials missing (RANDMAR_CLIENT_ID + secret file)"
        )

    fetched = 0
    with_images = 0
    without_images = 0
    skipped = 0
    errors = 0

    for i, sku in enumerate(skus):
        prior = completed.get(sku) or {}
        prior_ok = bool(prior.get("ok"))
        prior_count = int(prior.get("image_count") or 0)
        binaries_ok = bool(prior.get("binaries_ok"))
        if download_binaries and prior_ok and not force:
            if binaries_ok and sku_binaries_complete(out_dir, sku, prior_count):
                skipped += 1
                if prior_count >= 1:
                    with_images += 1
                else:
                    without_images += 1
                continue
            # URL-only prior run: fall through to download stills (may reuse url_map)
        elif (not download_binaries) and resume and not force and prior_ok:
            skipped += 1
            if prior_count >= 1:
                with_images += 1
            else:
                without_images += 1
            continue

        if i and sleep > 0:
            time.sleep(sleep)

        try:
            cached = url_map.get(sku) if resume and not force else None
            if (
                cached
                and isinstance(cached, dict)
                and isinstance(cached.get("images"), list)
                and cached.get("images")
            ):
                images = [
                    {
                        "image_id": r.get("image_id"),
                        "url": r.get("url"),
                        "is_primary": r.get("is_primary"),
                        "sort_order": r.get("sort_order"),
                        "file_name": r.get("file_name"),
                        "content_type": r.get("content_type"),
                        "content_length": r.get("content_length"),
                        "description": r.get("description"),
                    }
                    for r in cached["images"]
                    if isinstance(r, dict) and r.get("url")
                ]
            else:
                raw = rm.get_product_images(sku, use_token=use_token)
                images = normalize_image_urls(raw)

            if download_binaries and images:
                images = download_sku_stills(
                    rm=rm,
                    sku=sku,
                    images=images,
                    out_dir=out_dir,
                    sleep_sec=sleep,
                    use_token=use_token,
                )
            elif download_binaries and not images:
                # still write empty metadata for consistency
                dest = sku_image_dir(out_dir, sku)
                dest.mkdir(parents=True, exist_ok=True)
                _write_json(
                    dest / METADATA_NAME,
                    {
                        "sku": sku,
                        "endpoint_list": WORKING_ENDPOINT,
                        "endpoint_image": IMAGE_ENDPOINT,
                        "fetched_at": _utc_now(),
                        "image_count": 0,
                        "primary_image_id": None,
                        "images": [],
                        "urls": [],
                        "local_paths": [],
                    },
                )

            persist_sku_image_urls(conn, sku, images)
            url_map[sku] = {
                "sku": sku,
                "endpoint": WORKING_ENDPOINT,
                "image_endpoint": IMAGE_ENDPOINT,
                "fetched_at": _utc_now(),
                "image_count": len(images),
                "images": images,
                "urls": [row["url"] for row in images],
                "local_paths": [row.get("local_path") for row in images if row.get("local_path")],
                "primary_image_id": next(
                    (r.get("image_id") for r in images if r.get("is_primary")),
                    (images[0].get("image_id") if images else None),
                ),
            }
            completed[sku] = {
                "ok": True,
                "image_count": len(images),
                "binaries_ok": bool(download_binaries),
                "downloaded_count": len([r for r in images if r.get("local_path")])
                if download_binaries
                else 0,
                "fetched_at": _utc_now(),
            }
            failed.pop(sku, None)
            fetched += 1
            if images:
                with_images += 1
            else:
                without_images += 1
        except Exception as exc:  # noqa: BLE001
            errors += 1
            failed[sku] = {
                "ok": False,
                "error": type(exc).__name__,
                "message": str(exc)[:240],
                "at": _utc_now(),
            }
            logger.warning("image backfill failed for %s: %s", sku, type(exc).__name__)

        progress = {
            "snapshot_id": snapshot_id,
            "endpoint": WORKING_ENDPOINT,
            "image_endpoint": IMAGE_ENDPOINT,
            "public_noauth": not use_token,
            "download_binaries": download_binaries,
            "started_at": progress.get("started_at") or _utc_now(),
            "updated_at": _utc_now(),
            "completed": completed,
            "failed": failed,
            "counts": {
                "target": len(skus),
                "fetched_this_run": fetched,
                "skipped_resume": skipped,
                "with_images": with_images,
                "without_images": without_images,
                "errors": errors,
            },
        }
        # Checkpoint frequently so resume works after interruption.
        if (fetched + errors) % 5 == 0 or sku == skus[-1]:
            conn.commit()
            _write_json(progress_path, progress)
            _write_json(map_path, url_map)

    conn.commit()
    _write_json(progress_path, progress)
    _write_json(map_path, url_map)

    ge1 = 0
    ge1_local = 0
    for sku in skus:
        entry = url_map.get(sku) or {}
        n = int(entry.get("image_count") or 0)
        if n >= 1:
            ge1 += 1
        elif sku in completed and int(completed[sku].get("image_count") or 0) >= 1:
            ge1 += 1
            n = int(completed[sku].get("image_count") or 0)
        locals_ = entry.get("local_paths") or []
        if len([p for p in locals_ if p]) >= 1 or (
            download_binaries and sku_binaries_complete(out_dir, sku, max(n, 1))
        ):
            if n >= 1:
                ge1_local += 1

    summary = {
        "snapshot_id": snapshot_id,
        "cohort": COHORT_SAFE_NATIONWIDE,
        "pipeline_source": PIPELINE_RANDMAR_FIRST,
        "endpoint": WORKING_ENDPOINT,
        "image_endpoint": IMAGE_ENDPOINT,
        "public_noauth": not use_token,
        "download_binaries": download_binaries,
        "manufacturer_images_note": (
            "GET /V4/Manufacturer/{mfrId}/Product/{sku}/Images returns 401 "
            "with reseller OAuth; use public Product/Images + Product/Image/{id}. "
            "Never call GenerateImage / AppendImage / upload POSTs. "
            "Do not rotate secrets/randmar_api_key.txt for imagery."
        ),
        "target_skus": len(skus),
        "fetched_this_run": fetched,
        "skipped_resume": skipped,
        "skus_with_ge1_image_url": ge1,
        "skus_with_ge1_local_still": ge1_local,
        "skus_without_images": without_images
        if not resume
        else max(0, len(skus) - ge1 - errors),
        "errors": errors,
        "failed_skus": sorted(failed.keys()),
        "sleep_sec": sleep,
        "images_dir": str(out_dir),
        "map_path": str(map_path),
        "progress_path": str(progress_path),
        "live_listings_enabled": settings.live_listings_enabled,
        "supplier_orders_enabled": settings.supplier_orders_enabled,
        "finished_at": _utc_now(),
    }
    _write_json(out_dir / SUMMARY_NAME, summary)
    conn.close()
    return summary

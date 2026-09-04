"""Read-only probe of Randmar product image list endpoints. Never prints secrets."""
from __future__ import annotations

import json
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from firefinds.clients.randmar import RandmarClient
from firefinds.config import get_settings


def summarize_payload(raw: bytes, ctype: str) -> dict:
    if "json" in ctype or (raw[:1] in (b"[", b"{")):
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            return {"bytes": len(raw), "parse": "fail"}
        if isinstance(data, list):
            sample = data[0] if data and isinstance(data[0], dict) else None
            urls = []
            for item in data[:5]:
                if isinstance(item, dict) and item.get("Url"):
                    urls.append(str(item["Url"])[:120])
            return {
                "n": len(data),
                "sample_keys": list(sample.keys()) if sample else None,
                "sample_urls": urls,
                "primary_n": sum(
                    1 for i in data if isinstance(i, dict) and i.get("IsPrimary")
                ),
            }
        if isinstance(data, dict):
            keys = list(data.keys())
            imgish = {
                k: (type(data[k]).__name__ if not isinstance(data[k], (str, int, float, bool, type(None))) else data[k])
                for k in keys
                if "mage" in k.lower() or "url" in k.lower() or "media" in k.lower()
            }
            return {"keys": keys[:40], "imgish": imgish}
        return {"type": type(data).__name__}
    return {"bytes": len(raw), "ctype": ctype}


def probe(method: str, url: str, headers: dict) -> dict:
    req = urllib.request.Request(url, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            ctype = resp.headers.get("Content-Type", "")
            out = {"http": resp.status, "ctype": ctype}
            out.update(summarize_payload(raw, ctype))
            return out
    except urllib.error.HTTPError as exc:
        body = exc.read()[:180].decode("utf-8", "replace")
        return {"http": exc.code, "err_body": body}
    except Exception as exc:  # noqa: BLE001
        return {"error": type(exc).__name__, "msg": str(exc)[:120]}


def main() -> None:
    settings = get_settings()
    assert not settings.live_listings_enabled
    assert not settings.supplier_orders_enabled
    client = RandmarClient(settings)
    assert client.credentials_present()
    # acquire auth via client (value never printed)
    _ = client.fetch_token()
    headers = client._auth_headers(use_token=True)
    headers_noauth = {"Accept": "application/json"}

    conn = sqlite3.connect(str(settings.db_path))
    safe = [
        r[0]
        for r in conn.execute(
            """
            SELECT sku FROM candidate_cohorts
            WHERE cohort='SAFE_NATIONWIDE' AND snapshot_id='20260903_1744'
            ORDER BY IFNULL(rank, 999999), sku
            LIMIT 40
            """
        ).fetchall()
    ]
    want = set(safe)
    mfr: dict[str, str] = {}
    with open("/workspace/firefinds/data/products_all.json", encoding="utf-8") as fh:
        for row in json.load(fh):
            sku = row.get("RandmarSKU")
            if sku in want and row.get("ManufacturerId"):
                mfr[sku] = str(row["ManufacturerId"])

    base = settings.randmar_api_base.rstrip("/")
    reseller = settings.randmar_reseller_id
    sku0 = safe[0]
    mid0 = mfr.get(sku0, "x")
    print("probe_sku", sku0, "mfr", mid0)

    tests = [
        ("public_Images_auth", f"{base}/Product/{urllib.parse.quote(sku0, safe='')}/Images", headers),
        ("public_Images_noauth", f"{base}/Product/{urllib.parse.quote(sku0, safe='')}/Images", headers_noauth),
        ("public_Exists", f"{base}/Product/{urllib.parse.quote(sku0, safe='')}/Image/Exists", headers),
        (
            "mfr_Images",
            f"{base}/V4/Manufacturer/{urllib.parse.quote(mid0, safe='')}/Product/{urllib.parse.quote(sku0, safe='')}/Images",
            headers,
        ),
        (
            "reseller_Product",
            f"{base}/V4/Reseller/{urllib.parse.quote(reseller, safe='')}/Product/{urllib.parse.quote(sku0, safe='')}",
            headers,
        ),
    ]
    results = {}
    for name, url, hdrs in tests:
        results[name] = probe("GET", url, hdrs)
        print(name, json.dumps(results[name], default=str)[:600])
        time.sleep(0.4)

    hits = empty = 0
    errs: dict[str, int] = {}
    first_hit = None
    for sku in safe[:12]:
        url = f"{base}/Product/{urllib.parse.quote(sku, safe='')}/Images"
        r = probe("GET", url, headers)
        if r.get("http") == 200 and (r.get("n") or 0) > 0:
            hits += 1
            if first_hit is None:
                first_hit = {"sku": sku, **r}
        elif r.get("http") == 200:
            empty += 1
        else:
            key = str(r.get("http") or r.get("error"))
            errs[key] = errs.get(key, 0) + 1
        time.sleep(0.35)
    print("sample12", {"hits": hits, "empty": empty, "errs": errs, "first_hit": first_hit})

    out = Path("/workspace/firefinds/data/images/_probe_results.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {"endpoint_tests": results, "sample12": {"hits": hits, "empty": empty, "errs": errs, "first_hit": first_hit}},
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print("wrote", out)


if __name__ == "__main__":
    main()

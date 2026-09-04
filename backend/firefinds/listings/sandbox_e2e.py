"""Sandbox Sell Inventory + Offer E2E for Final 5 (never publish / never Process)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from firefinds.clients.ebay import (
    EbayApiError,
    EbayClient,
    EbayListingsDisabled,
    EbayPublishDisabled,
    EbayUserOAuthNotConfigured,
)
from firefinds.config import PROJECT_ROOT, Settings, get_settings

FINAL5_V21_SKUS: tuple[str, ...] = (
    "0ZD3500TRC638MEF8GM5",
    "U2FXR9B3X0GWJ4QZHY7K",
    "F5ON8QFP5D4DP8TDEPYZ",
    "Y37ECLH683SESD119MDT",
    "O5GXH5VHEFJZZ71YR7MZ",
)

DEFAULT_DRAFT_DIR = (
    PROJECT_ROOT
    / "data"
    / "drafts"
    / "randmar_first"
    / "safe_nationwide"
    / "final5_v2_original"
)


def _policy_overrides() -> dict[str, str]:
    """Optional env overrides for offer listingPolicies / categoryId."""
    out: dict[str, str] = {}
    mapping = {
        "EBAY_FULFILLMENT_POLICY_ID": "fulfillmentPolicyId",
        "EBAY_PAYMENT_POLICY_ID": "paymentPolicyId",
        "EBAY_RETURN_POLICY_ID": "returnPolicyId",
        "EBAY_CATEGORY_ID": "categoryId",
    }
    for env_key, field in mapping.items():
        raw = (os.environ.get(env_key) or "").strip()
        if raw and raw.lower() != "placeholder":
            out[field] = raw
    return out


def _apply_offer_overrides(offer: dict[str, Any]) -> dict[str, Any]:
    o = dict(offer)
    overrides = _policy_overrides()
    if "categoryId" in overrides:
        o["categoryId"] = overrides["categoryId"]
    policies = dict(o.get("listingPolicies") or {})
    for key in ("fulfillmentPolicyId", "paymentPolicyId", "returnPolicyId"):
        if key in overrides:
            policies[key] = overrides[key]
    if policies:
        o["listingPolicies"] = policies
    return o


def _draft_path(drafts_dir: Path, sku: str) -> Path:
    return drafts_dir / f"{sku}.ORIGINAL_SUPPLIER.json"


def _load_draft(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"draft is not an object: {path}")
    return data


def _err_payload(exc: BaseException) -> dict[str, Any]:
    if isinstance(exc, EbayApiError):
        return exc.to_dict()
    return {
        "message": str(exc)[:500],
        "type": type(exc).__name__,
    }


def run_sandbox_inventory_offer_e2e(
    *,
    settings: Settings | None = None,
    skus: tuple[str, ...] | list[str] | None = None,
    drafts_dir: Path | None = None,
    assert_publish_refused: bool = True,
    client: EbayClient | None = None,
) -> dict[str, Any]:
    """Create/replace inventory + try offer for Final 5; assert publish refused.

    Never flips gates. Never prints secrets. If Business Policy blocks offers,
    inventory results are still recorded and the eBay error is kept as blocker.
    """
    settings = settings or get_settings()
    client = client or EbayClient(settings)
    skus = tuple(skus) if skus is not None else FINAL5_V21_SKUS
    drafts_dir = Path(drafts_dir) if drafts_dir else DEFAULT_DRAFT_DIR
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    gate_snapshot = {
        "LIVE_LISTINGS_ENABLED": bool(settings.live_listings_enabled),
        "EBAY_SANDBOX_PUBLISH_ENABLED": bool(settings.ebay_sandbox_publish_enabled),
        "EBAY_PRODUCTION_ENABLED": bool(settings.ebay_production_enabled),
        "SUPPLIER_ORDERS_ENABLED": bool(settings.supplier_orders_enabled),
        "EBAY_ENV": settings.ebay_env,
        "user_refresh_token_present": client.user_refresh_token_present(),
        "policy_overrides_present": sorted(_policy_overrides().keys()),
    }

    results: list[dict[str, Any]] = []
    inventory_ok = 0
    offer_ok = 0
    publish_refused = 0
    blockers: list[dict[str, Any]] = []

    for sku in skus:
        row: dict[str, Any] = {"sku": sku}
        path = _draft_path(drafts_dir, sku)
        row["draft_path"] = str(path)
        if not path.is_file():
            row["inventory"] = {"ok": False, "error": {"message": "draft missing"}}
            row["offer"] = {"ok": False, "skipped": True}
            row["publish"] = {"ok": False, "skipped": True}
            results.append(row)
            blockers.append({"sku": sku, "stage": "draft", "error": "draft missing"})
            continue

        try:
            draft = _load_draft(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            row["inventory"] = {"ok": False, "error": _err_payload(exc)}
            row["offer"] = {"ok": False, "skipped": True}
            row["publish"] = {"ok": False, "skipped": True}
            results.append(row)
            blockers.append({"sku": sku, "stage": "draft", "error": str(exc)[:300]})
            continue

        inv_payload = draft.get("inventory_item") or {}
        offer_payload = _apply_offer_overrides(dict(draft.get("offer") or {}))
        if not offer_payload.get("sku"):
            offer_payload["sku"] = sku

        # --- inventory ---
        try:
            inv_result = client.create_or_replace_inventory_item(sku, inv_payload)
            row["inventory"] = {"ok": True, "result_keys": sorted(inv_result.keys())}
            inventory_ok += 1
        except (
            EbayListingsDisabled,
            EbayUserOAuthNotConfigured,
            EbayApiError,
            RuntimeError,
            ValueError,
        ) as exc:
            row["inventory"] = {"ok": False, "error": _err_payload(exc)}
            blockers.append(
                {"sku": sku, "stage": "inventory", "error": _err_payload(exc)}
            )
            row["offer"] = {"ok": False, "skipped": True}
            row["publish"] = {"ok": False, "skipped": True}
            results.append(row)
            continue

        # --- offer ---
        offer_id: str | None = None
        try:
            offer_result = client.create_or_update_offer(offer_payload)
            offer_id = str(
                (offer_result or {}).get("offerId")
                or (offer_result or {}).get("offer_id")
                or ""
            ).strip() or None
            row["offer"] = {
                "ok": True,
                "offer_id_present": bool(offer_id),
                "updated": bool((offer_result or {}).get("updated")),
                "result_keys": sorted((offer_result or {}).keys()),
            }
            offer_ok += 1
        except (
            EbayListingsDisabled,
            EbayUserOAuthNotConfigured,
            EbayApiError,
            RuntimeError,
            ValueError,
        ) as exc:
            err = _err_payload(exc)
            row["offer"] = {"ok": False, "error": err}
            blockers.append({"sku": sku, "stage": "offer", "error": err})

        # --- publish (must refuse while gate OFF) ---
        if assert_publish_refused:
            try:
                client.publish_offer(offer_id or "e2e-assert-refused")
                row["publish"] = {
                    "ok": False,
                    "refused": False,
                    "error": {"message": "publish unexpectedly allowed"},
                }
                blockers.append(
                    {
                        "sku": sku,
                        "stage": "publish",
                        "error": "publish unexpectedly allowed",
                    }
                )
            except EbayPublishDisabled as exc:
                row["publish"] = {
                    "ok": True,
                    "refused": True,
                    "message": str(exc)[:300],
                }
                publish_refused += 1
            except EbayListingsDisabled as exc:
                # Still a refuse — acceptable if production gates trip
                row["publish"] = {
                    "ok": True,
                    "refused": True,
                    "message": str(exc)[:300],
                }
                publish_refused += 1
            except Exception as exc:  # noqa: BLE001 — record unexpected
                row["publish"] = {
                    "ok": False,
                    "refused": False,
                    "error": _err_payload(exc),
                }
                blockers.append(
                    {"sku": sku, "stage": "publish", "error": _err_payload(exc)}
                )
        else:
            row["publish"] = {"ok": False, "skipped": True}

        results.append(row)

    n = len(skus)
    # Prefer a stable Business Policy / registration blocker summary
    offer_blocker_summary = None
    for b in blockers:
        if b.get("stage") == "offer":
            err = b.get("error") or {}
            if isinstance(err, dict):
                offer_blocker_summary = (
                    err.get("message")
                    or str(err)[:300]
                )
            else:
                offer_blocker_summary = str(err)[:300]
            break

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "timestamp": ts,
        "skus": list(skus),
        "drafts_dir": str(drafts_dir),
        "gates": gate_snapshot,
        "summary": {
            "inventory_ok": inventory_ok,
            "inventory_total": n,
            "offer_ok": offer_ok,
            "offer_total": n,
            "publish_refused": publish_refused,
            "publish_total": n if assert_publish_refused else 0,
            "offer_blocker": offer_blocker_summary,
        },
        "results": results,
        "blockers": blockers,
    }
    return report


def write_e2e_reports(
    report: dict[str, Any],
    *,
    reports_dir: Path | None = None,
) -> dict[str, str]:
    """Write JSON + Markdown reports under data/reports/."""
    reports_dir = Path(reports_dir) if reports_dir else PROJECT_ROOT / "data" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    ts = report.get("timestamp") or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stem = f"sandbox_inventory_offer_e2e_{ts}"
    json_path = reports_dir / f"{stem}.json"
    md_path = reports_dir / f"{stem}.md"

    json_path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")

    s = report["summary"]
    lines = [
        f"# Sandbox inventory/offer E2E ({ts})",
        "",
        f"Generated: `{report.get('generated_at')}`",
        "",
        "## Gates (must stay OFF for publish/orders)",
        "",
    ]
    for k, v in (report.get("gates") or {}).items():
        lines.append(f"- `{k}`: `{v}`")
    lines += [
        "",
        "## Summary",
        "",
        f"- **inventory:** {s['inventory_ok']}/{s['inventory_total']} OK",
        f"- **offer:** {s['offer_ok']}/{s['offer_total']} OK",
        f"- **publish:** {s['publish_refused']}/{s['publish_total']} confirmed refused",
    ]
    if s.get("offer_blocker"):
        lines.append(f"- **offer blocker:** {s['offer_blocker']}")
    lines += ["", "## Per-SKU", ""]
    for row in report.get("results") or []:
        inv = row.get("inventory") or {}
        off = row.get("offer") or {}
        pub = row.get("publish") or {}
        inv_s = "OK" if inv.get("ok") else f"FAIL: {(inv.get('error') or {}).get('message', inv)}"
        if off.get("skipped"):
            off_s = "skipped"
        elif off.get("ok"):
            off_s = "OK"
        else:
            off_s = f"FAIL: {(off.get('error') or {}).get('message', off)}"
        if pub.get("skipped"):
            pub_s = "skipped"
        elif pub.get("refused"):
            pub_s = "refused (expected)"
        else:
            pub_s = f"UNEXPECTED: {pub}"
        lines.append(f"### `{row.get('sku')}`")
        lines.append(f"- inventory: {inv_s}")
        lines.append(f"- offer: {off_s}")
        lines.append(f"- publish: {pub_s}")
        lines.append("")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": str(json_path), "md": str(md_path)}

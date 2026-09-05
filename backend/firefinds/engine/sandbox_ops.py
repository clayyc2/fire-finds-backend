"""Read-only Sandbox ops and fixture-driven lifecycle. No mutations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from firefinds.clients.ebay import EbayClient
from firefinds.config import Settings
from firefinds.engine.capacity_live import SellingLimitSnapshot, parse_privilege_payload
from firefinds.engine.order_ingest import dry_run_lifecycle
from firefinds.engine.services import Audit

CAPACITY_FILE = Path("data/capacity_live.json")


def persist_privilege(snapshot: SellingLimitSnapshot, path: Path = CAPACITY_FILE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": snapshot.source,
        "seller_registration_completed": snapshot.seller_registration_completed,
        "quantity": snapshot.quantity,
        "amount_cad": None if snapshot.amount_cad is None else str(snapshot.amount_cad),
        "has_live_cap": snapshot.has_live_cap,
        "guessed": False,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def sanitized_read_report(client: EbayClient) -> dict[str, Any]:
    status = client.sandbox_status()
    report: dict[str, Any] = {
        "token_present": bool(status.get("user_refresh_token_present")),
        "ebay_env": status.get("ebay_env"),
        "marketplace_id": status.get("marketplace_id"),
        "gates": {
            "LIVE_LISTINGS_ENABLED": status.get("live_listings_enabled"),
            "EBAY_SANDBOX_PUBLISH_ENABLED": status.get("ebay_sandbox_publish_enabled"),
            "EBAY_PRODUCTION_ENABLED": status.get("ebay_production_enabled"),
            "EBAY_TRACKING_UPDATES_ENABLED": status.get("ebay_tracking_updates_enabled"),
        },
        "reads": {},
        "skipped": False,
    }
    if not report["token_present"]:
        report["skipped"] = True
        report["reason"] = "user_refresh_token_missing"
        return report
    probes = {
        "privilege": client.get_privileges,
        "orders": lambda: client.get_orders(limit=10),
        "policies": client.get_business_policies,
        "locations": client.list_inventory_locations,
        "payments_program": client.get_payments_program,
    }
    for name, fn in probes.items():
        try:
            body = fn()
            keys = sorted(body.keys()) if isinstance(body, dict) else []
            report["reads"][name] = {"ok": True, "keys": keys}
            if name == "privilege" and isinstance(body, dict):
                snap = parse_privilege_payload(body)
                persist_privilege(snap)
                report["reads"][name]["selling_limit_quantity"] = snap.quantity
                report["reads"][name]["has_live_cap"] = snap.has_live_cap
                report["reads"][name]["seller_registration_completed"] = snap.seller_registration_completed
            if name == "orders" and isinstance(body, dict):
                report["reads"][name]["order_count"] = len(body.get("orders") or [])
            if name == "policies" and isinstance(body, dict):
                report["reads"][name]["policy_groups"] = sorted(body.keys())
        except Exception as exc:
            report["reads"][name] = {"ok": False, "error_type": type(exc).__name__}
    return report


def fixture_lifecycle(settings: Settings, fixture: Path, out_dir: Path) -> dict[str, Any]:
    order = json.loads(fixture.read_text(encoding="utf-8"))
    audit = Audit(out_dir / "ingest_audit.jsonl")
    store = out_dir / "ingest_orders.json"
    result = dry_run_lifecycle(settings, audit, store, order)
    result["fixture"] = str(fixture)
    (out_dir / "lifecycle_report.json").write_text(
        json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
    )
    return result

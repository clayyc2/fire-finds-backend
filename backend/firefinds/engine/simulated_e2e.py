"""Simulated no-write lifecycle: import → score → capacity → ingest → record.

Never calls ProcessNew, publishOffer, or createShippingFulfillment.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from firefinds.config import Settings
from firefinds.engine.capacity_live import apply_live_caps, parse_privilege_payload
from firefinds.engine.order_ingest import ROUTED_OFF, dry_run_lifecycle
from firefinds.engine.sandbox_ops import persist_privilege
from firefinds.engine.services import (
    Audit,
    CapacityManager,
    OpportunityEngine,
    RandmarImporter,
)


def run_simulated_e2e(
    *,
    settings: Settings,
    catalog_path: Path,
    privilege_path: Path,
    order_path: Path,
    out_dir: Path,
) -> dict[str, Any]:
    switches = (settings.live_listings_enabled, settings.ebay_sandbox_publish_enabled,
                settings.ebay_production_enabled, settings.ebay_tracking_updates_enabled,
                settings.supplier_orders_enabled)
    if any(switches) or not settings.dry_run or not settings.global_kill_switch:
        raise ValueError("simulated E2E requires dry-run, global kill, and all write gates OFF")
    out_dir.mkdir(parents=True, exist_ok=True)
    audit = Audit(out_dir / "e2e_audit.jsonl")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    privilege = json.loads(privilege_path.read_text(encoding="utf-8"))
    order = json.loads(order_path.read_text(encoding="utf-8"))
    snap = parse_privilege_payload(privilege)
    persist_privilege(snap, out_dir / "capacity_live.json")
    item_cap, value_cap = apply_live_caps(
        configured_item_limit=settings.monthly_item_limit,
        configured_value_limit_cad=float(settings.monthly_value_limit_cad or 0),
        snapshot=snap,
    )
    candidates = RandmarImporter(audit).normalize(catalog)
    engine = OpportunityEngine(settings)
    decisions = [engine.evaluate(c) for c in candidates]
    selected = CapacityManager(
        settings, live_item_limit=item_cap, live_value_limit_cad=value_cap
    ).select(decisions)
    ingest = dry_run_lifecycle(settings, audit, out_dir / "ingest_orders.json", order)
    selected_skus = [d.sku for d in selected]
    performance = {
        "ebay_order_id": ingest.get("ebay_order_id"),
        "sku": ingest.get("sku"),
        "state": ingest.get("state"),
        "capacity_item_cap": item_cap,
        "capacity_value_cap": value_cap,
        "selected_skus": selected_skus,
        "sku_was_in_capacity": ingest.get("sku") in selected_skus,
        "process_called": False,
        "tracking_posted": False,
        "publish_called": False,
        "simulated_fulfillment": {
            "prepared": False,
            "carrier": None,
            "tracking_number": None,
            "posted": False,
            "reason": "shipment_evidence_not_available",
        },
        "live_sandbox_gets": "pending",
        "gates": {
            "LIVE_LISTINGS_ENABLED": settings.live_listings_enabled,
            "EBAY_SANDBOX_PUBLISH_ENABLED": settings.ebay_sandbox_publish_enabled,
            "EBAY_PRODUCTION_ENABLED": settings.ebay_production_enabled,
            "EBAY_TRACKING_UPDATES_ENABLED": settings.ebay_tracking_updates_enabled,
            "SUPPLIER_ORDERS_ENABLED": settings.supplier_orders_enabled,
        },
    }
    (out_dir / "simulated_e2e.json").write_text(
        json.dumps(performance, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )
    audit.write("simulated_e2e", performance)
    assert ingest.get("state") == ROUTED_OFF
    assert all(v is False for v in performance["gates"].values())
    return performance

"""One deterministic scheduled cycle. This deployment profile cannot purchase.

Refresh catalogue/start prices hourly and check own orders every invocation.
It is preparation/monitoring infrastructure, NOT live automatic fulfillment.
"""
from __future__ import annotations

import json
from pathlib import Path
import time

from firefinds.engine.catalogue_queue import build_catalogue_queue
from firefinds.engine.starting_prices import price_queue
from firefinds.engine.storage import atomic_json, checkpoint_lock
from firefinds.fulfillment.sweep import sweep_orders


def run_cycle(*, ebay, supplier, worker, settings, mapping, root: Path,
              purchase_denied_skus=(), clock=time.time):
    root = Path(root)
    with checkpoint_lock(root / "cycle"):
        started = clock()
        status = {"started_at": started, "finished_at": None, "errors": [],
                  "mode": "read_only_preparation", "automatic_purchases_enabled": False,
                  "publishing_enabled": False, "ai_required": False}
        # Order checks remain independent of a failed catalogue refresh.
        try:
            orders = sweep_orders(ebay=ebay, worker=worker, report_path=root / "orders.json")
            status.update(orders_checked=orders["orders_checked"],
                          orders_needing_attention=orders["needs_attention"],
                          order_sweep_complete=orders["complete"])
            if not orders["complete"]:
                status["errors"].append("order_sweep_incomplete")
        except Exception as exc:
            status["errors"].append("orders:" + type(exc).__name__)
        try:
            path = root / "catalogue.json"
            cached = json.loads(path.read_text()) if path.exists() else None
            observed = cached.get("observed_at") if isinstance(cached, dict) else None
            if (type(observed) not in (int, float) or
                    not 0 <= clock() - observed < settings.repricing_cadence_sec):
                observed = clock()
                rows = supplier.get_products_json()
                if not isinstance(rows, list) or not rows:
                    raise ValueError("Catalogue unavailable")
                cached = {"source": "randmar.v4.report.products.json", "observed_at": observed, "rows": rows}
                # Validate and price before replacing a previous good snapshot.
            queue = build_catalogue_queue(cached["rows"], existing_skus=mapping,
                purchase_denied_skus=purchase_denied_skus, stock_buffer=settings.stock_buffer,
                initial_quantity=settings.initial_listing_quantity)
            queue["catalogue_observed_at"] = observed
            priced = price_queue(queue, cached["rows"], settings)
            atomic_json(root / "starting-prices.json", priced)
            atomic_json(path, cached)
            status.update(catalogue_observed_at=observed, priced_candidates=priced["priced_count"])
        except Exception as exc:
            status["errors"].append("prices:" + type(exc).__name__)
        status["finished_at"] = clock()
        status["needs_attention"] = bool(status["errors"] or status.get("orders_needing_attention", 0))
        # Local durable alert; external alert delivery is not claimed.
        atomic_json(root / "attention.json", {"observed_at": clock(),
            "needs_attention": status["needs_attention"], "errors": status["errors"],
            "orders_needing_attention": status.get("orders_needing_attention")})
        atomic_json(root / "status.json", status)
        return status

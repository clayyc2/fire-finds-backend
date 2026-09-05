"""Bounded order discovery feeding the connected worker; restart at page zero."""
from __future__ import annotations

import time
from firefinds.engine.storage import atomic_json


def sweep_orders(*, ebay, worker, report_path, page_size=50, max_pages=20):
    if type(page_size) is not int or not 1 <= page_size <= 200 or type(max_pages) is not int or not 1 <= max_pages <= 100:
        raise ValueError("Explicit bounded pagination required")
    report = {"observed_at": time.time(), "complete": False, "pages": 0, "results": [],
              "window": "API default order lookback; not an all-time audit"}
    seen = set()
    try:
        for page in range(max_pages):
            body = ebay.get_orders(limit=page_size, offset=page * page_size)
            rows = body.get("orders") if isinstance(body, dict) else None
            if not isinstance(rows, list):
                raise ValueError("Malformed order page")
            for order in rows:
                oid = order.get("orderId") if isinstance(order, dict) else None
                if not isinstance(oid, str) or not oid.strip() or oid in seen:
                    # Overlap means the paging view shifted; a new sweep must
                    # restart. Never call this a complete consistent scan.
                    raise ValueError("Invalid or repeated order identity")
                seen.add(oid)
                report["results"].append(worker.run_order(oid))
                atomic_json(report_path, report)
            report["pages"] += 1
            total = body.get("total")
            if total is not None and (type(total) is not int or total < 0):
                raise ValueError("Invalid order total")
            if not rows or (total is not None and (page * page_size + len(rows)) >= total) or (
                    total is None and not body.get("next") and len(rows) < page_size):
                report["complete"] = True
                break
        if not report["complete"]:
            report["error"] = "page_budget_reached"
    except Exception as exc:
        report["error"] = type(exc).__name__
    report["orders_checked"] = len(report["results"])
    report["needs_attention"] = sum(r["state"] != "FULFILLED" for r in report["results"])
    atomic_json(report_path, report)
    return report

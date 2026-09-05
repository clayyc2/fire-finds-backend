"""Bounded read-only eBay order sweep, with durable per-order checkpoints.

Each sweep restarts at page zero because eBay offset pages can shift as orders
arrive. Previously checkpointed orders are harmless replays. No submitter or
tracking writer is accepted by this service.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from .order_ingest import BLOCKED, OrderIngest
from .storage import atomic_json


def poll_orders(*, client, ingest: OrderIngest, sku_mapping: dict[str, str],
                progress_path: Path, max_pages: int = 20, page_size: int = 50):
    if not 1 <= page_size <= 200 or max_pages < 1:
        raise ValueError("invalid pagination bounds")
    if not isinstance(sku_mapping, dict) or any(
        not isinstance(k, str) or not k.strip() or not isinstance(v, str) or not v.strip()
        for k, v in sku_mapping.items()
    ):
        raise ValueError("explicit merchant SKU to Randmar SKU mapping required")
    report = {"pages": 0, "orders": 0, "blocked": 0, "complete": False,
              "submitted": False, "tracking_posted": False}
    seen_pages = set()
    for page in range(max_pages):
        offset = page * page_size
        try:
            body = client.get_orders(limit=page_size, offset=offset)
            if not isinstance(body, dict) or not isinstance(body.get("orders"), list):
                raise ValueError("invalid eBay order page")
            orders = body["orders"]
            ids = tuple(str(row.get("orderId") or "") for row in orders if isinstance(row, dict))
            if len(ids) != len(orders) or any(not oid for oid in ids):
                raise ValueError("invalid eBay order identity")
            if ids and ids in seen_pages:
                raise ValueError("repeated eBay page")
            seen_pages.add(ids)
            for raw in orders:
                order = deepcopy(raw)
                for line in order.get("lineItems") or []:
                    if isinstance(line, dict):
                        # Unknown mappings become blocked, never inferred from IDs.
                        line["sku"] = sku_mapping.get(line.get("sku"), "")
                record = ingest.ingest(order)
                report["orders"] += 1
                report["blocked"] += int(record.state == BLOCKED)
            report["pages"] += 1
            total = body.get("total")
            done = (not orders or (type(total) is int and offset + len(orders) >= total)
                    or (total is None and not body.get("next") and len(orders) < page_size))
            report["complete"] = done
            atomic_json(progress_path, report)
            if done:
                break
        except Exception as exc:
            report.update(error_type=type(exc).__name__, failed_offset=offset)
            atomic_json(progress_path, report)
            ingest.audit.write("order_poll_failed", report)
            raise
    if not report["complete"]:
        report["reason"] = "page_budget_reached"
    atomic_json(progress_path, report)
    ingest.audit.write("order_poll_finished", report)
    return report

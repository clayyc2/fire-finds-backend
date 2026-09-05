"""Deterministic Order Router using official Randmar V4 paths.

Submission (ProcessNew) stays off until SUPPLIER_ORDERS_ENABLED and an explicit
live-test flag. eBay order id is the immutable PO / idempotency key.
"""

from __future__ import annotations

from typing import Any

from firefinds.config import Settings
from firefinds.fulfillment.randmar_checkout import RandmarOrderProbe, po_for_ebay_order

DISPLAY_NAME_IDS = frozenset({"Fire Finds catalog read"})


class OrderRouterNotReady(RuntimeError):
    pass


def assert_dedicated_client_id(settings: Settings) -> None:
    cid = (settings.randmar_client_id or "").strip()
    if not cid or cid in DISPLAY_NAME_IDS:
        raise OrderRouterNotReady(
            "RANDMAR_CLIENT_ID must be the Dashboard Client ID, not a display name"
        )


def route_paid_ebay_order(
    client: Any,
    settings: Settings,
    *,
    ebay_order_id: str,
    sku: str,
    qty: int,
    ship_to: dict[str, str],
    submit_live: bool = False,
) -> dict[str, Any]:
    assert_dedicated_client_id(settings)
    probe = RandmarOrderProbe(client, settings)
    report = probe.run(
        ebay_order_id=ebay_order_id,
        sku=sku,
        qty=qty,
        ship_to=ship_to,
        cleanup_cart=not submit_live,
    )
    report["idempotency_key"] = po_for_ebay_order(ebay_order_id)
    if submit_live:
        report["status"] = "SUBMIT_REFUSED"
        report["note"] = (
            "Live ProcessNew is not enabled in this router build. "
            "Set a controlled live-test after probe PASS."
        )
    report["process_called"] = False
    return report

"""Validate shipment evidence before preparing a tracking update; no writes."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation


def prepare_tracking(*, order, supplier_sku: str, supplier_order_number: str,
                     shipments: list, carrier_mapping: dict[str, str]) -> dict:
    """Require one complete shipment for one explicitly mapped order line.

    Partial/multi-line shipments are held until their quantity accounting is
    implemented. Carrier IDs must come from an explicit Randmar/eBay mapping.
    """
    def hold(reason):
        return {"prepared": False, "reason": reason, "posted": False}
    oid = order.get("orderId")
    lines = order.get("lineItems") or []
    if not oid or not supplier_sku or not supplier_order_number:
        return hold("missing_order_mapping")
    if not isinstance(lines, list) or len(lines) != 1 or not isinstance(lines[0], dict):
        return hold("single_line_order_required")
    line = lines[0]
    qty = line.get("quantity")
    if not line.get("lineItemId") or type(qty) is not int or qty <= 0:
        return hold("invalid_order_line")
    if not isinstance(shipments, list):
        return hold("invalid_shipment_response")
    matched = []
    for row in shipments:
        if not isinstance(row, dict):
            return hold("invalid_shipment_row")
        if row.get("PONumber") == oid and row.get("OrderNumber") == supplier_order_number:
            if row.get("RandmarSKU") != supplier_sku:
                return hold("shipment_sku_mismatch")
            if row not in matched:
                matched.append(row)
    if len(matched) != 1:
        return hold("single_confirmed_shipment_required")
    row = matched[0]
    try:
        shipped = Decimal(str(row.get("QuantityShipped")))
    except (InvalidOperation, ValueError):
        return hold("invalid_shipped_quantity")
    if not shipped.is_finite() or shipped != qty:
        return hold("partial_or_excess_shipment")
    tracking = row.get("TrackingNumber")
    carrier = carrier_mapping.get(str(row.get("ShipVia") or ""))
    if not isinstance(tracking, str) or not tracking.strip() or not isinstance(carrier, str) or not carrier.strip():
        return hold("missing_tracking_or_verified_carrier")
    return {"prepared": True, "posted": False, "reason": "held_before_tracking_post",
            "order_id": oid, "payload": {"shippingCarrierCode": carrier,
                "trackingNumber": tracking.strip(),
                "lineItems": [{"lineItemId": line["lineItemId"], "quantity": qty}]}}

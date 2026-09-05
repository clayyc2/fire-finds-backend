"""Official remaining allowance, distinct from the headline Account API cap."""
from __future__ import annotations

from decimal import Decimal as D, InvalidOperation
import time
import xml.etree.ElementTree as ET

NS = {"e": "urn:ebay:apis:eBLBaseComponents"}


def parse_remaining_capacity(xml_bytes, *, observed_at):
    if len(xml_bytes) > 1_000_000 or b"<!DOCTYPE" in xml_bytes.upper() or b"<!ENTITY" in xml_bytes.upper():
        raise ValueError("Unexpected capacity response")
    root = ET.fromstring(xml_bytes)
    if root.tag != "{urn:ebay:apis:eBLBaseComponents}GetMyeBaySellingResponse":
        raise ValueError("Wrong capacity response identity")
    result = {"source": "Trading.GetMyeBaySelling.Summary", "observed_at": observed_at,
              "complete": False, "remaining_quantity": None, "remaining_amount_cad": None,
              "commerce_writes": False}
    # Partial/warning/error responses cannot authorize additional listings.
    if root.findtext("e:Ack", namespaces=NS) != "Success" or root.findall("e:Errors", NS):
        result["reason"] = "capacity_api_not_clean_success"
        return result
    if len(root.findall("e:Summary", NS)) != 1:
        result["reason"] = "missing_or_ambiguous_capacity_summary"
        return result
    summary = root.find("e:Summary", NS)
    qty_nodes = summary.findall("e:QuantityLimitRemaining", NS)
    amount_nodes = summary.findall("e:AmountLimitRemaining", NS)
    if len(qty_nodes) != 1 or len(amount_nodes) != 1:
        result["reason"] = "remaining_capacity_fields_unavailable"
        return result
    try:
        quantity, amount = D(qty_nodes[0].text), D(amount_nodes[0].text)
        if (not quantity.is_finite() or quantity < 0 or quantity != quantity.to_integral_value() or
                not amount.is_finite() or amount < 0 or amount_nodes[0].get("currencyID") != "CAD"):
            raise ValueError("Invalid remaining capacity")
    except (InvalidOperation, TypeError, ValueError):
        result["reason"] = "invalid_or_non_cad_capacity"
        return result
    result.update(complete=True, remaining_quantity=int(quantity), remaining_amount_cad=str(amount))
    return result


def available_after_reservations(snapshot, *, reserved_quantity=0, reserved_value_cad=D(0),
                                 now=None, max_age_sec=60):
    """Stale/incomplete capacity never becomes unlimited. A shared publisher
    ledger must supply ALL pending reservations; this function doesn't publish.
    """
    now = time.time() if now is None else now
    observed = snapshot.get("observed_at")
    if (snapshot.get("complete") is not True or type(observed) not in (int, float) or
            not 0 <= now - observed <= max_age_sec):
        return None
    quantity = snapshot.get("remaining_quantity")
    amount = D(str(snapshot.get("remaining_amount_cad")))
    if (type(quantity) is not int or quantity < 0 or not amount.is_finite() or amount < 0 or
            type(reserved_quantity) is not int or reserved_quantity < 0 or
            not isinstance(reserved_value_cad, D) or not reserved_value_cad.is_finite() or reserved_value_cad < 0):
        raise ValueError("Invalid allowance or reservations")
    return max(0, quantity-reserved_quantity), max(D(0), amount-reserved_value_cad)

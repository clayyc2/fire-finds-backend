"""Thin official-path helpers on top of RandmarClient. No Process*."""

from __future__ import annotations

from urllib.parse import quote
from typing import Any


def order_by_po(client: Any, reseller_po: str) -> Any:
    url = client._reseller_path(f"/Order/PONumber/{quote(str(reseller_po), safe='')}")
    return client._request_json("GET", url, timeout=60, label="Randmar Order/PONumber")


def order_by_number(client: Any, order_number: str) -> Any:
    url = client._reseller_path(f"/Order/{quote(str(order_number), safe='')}")
    return client._request_json("GET", url, timeout=60, label="Randmar Order")


def list_shipments(client: Any) -> Any:
    url = client._reseller_path("/Orders/Shipments")
    return client._request_json("GET", url, timeout=60, label="Randmar Orders/Shipments")

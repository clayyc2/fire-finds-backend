"""Randmar shipping quotes + landed cost.

HARD RULE: do not invent marketing flat rates (e.g. $10) as the true shipping
cost. Prefer read-only Randmar estimate endpoints:

  - POST .../Cart/ShippingMethods/{cartName}  (after AddItem; never Process)
  - POST .../ShippingLabel/Estimate
  - POST .../Order/{orderNumber}/ShipVia/Estimate  (existing orders only)

If no real quote is available, status is UNRESOLVED and the SKU must not be
classified as finally profitable / finally listable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence

WAREHOUSE_FIELDS = (
    ("Montreal", "qty_montreal"),
    ("Toronto", "qty_toronto"),
    ("Vancouver", "qty_vancouver"),
    ("Laval", "qty_laval"),
    ("Edmonton", "qty_edmonton"),
)

WAREHOUSE_PREFER = ("Toronto", "Montreal", "Laval", "Edmonton", "Vancouver")

# Approximate warehouse origin addresses for ShippingLabel/Estimate (public).
WAREHOUSE_ORIGINS: dict[str, dict[str, str]] = {
    "Montreal": {
        "Name": "Randmar Montreal",
        "Street1": "1000 Rue Ottawa",
        "City": "Montreal",
        "Province": "QC",
        "PostalCode": "H3C1M7",
        "Country": "CA",
    },
    "Laval": {
        "Name": "Randmar Laval",
        "Street1": "1000 Blvd St-Martin",
        "City": "Laval",
        "Province": "QC",
        "PostalCode": "H7S1M7",
        "Country": "CA",
    },
    "Toronto": {
        "Name": "Randmar Toronto",
        "Street1": "100 King St W",
        "City": "Toronto",
        "Province": "ON",
        "PostalCode": "M5X1A9",
        "Country": "CA",
    },
    "Edmonton": {
        "Name": "Randmar Edmonton",
        "Street1": "100 Street NW",
        "City": "Edmonton",
        "Province": "AB",
        "PostalCode": "T5J0N3",
        "Country": "CA",
    },
    "Vancouver": {
        "Name": "Randmar Vancouver",
        "Street1": "100 West Georgia St",
        "City": "Vancouver",
        "Province": "BC",
        "PostalCode": "V6B0N9",
        "Country": "CA",
    },
}

STATUS_RESOLVED = "RESOLVED"
STATUS_UNRESOLVED = "UNRESOLVED"


def _f(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _i(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def pick_fulfillment_warehouse(product: Mapping[str, Any]) -> str | None:
    """Choose warehouse with the most on-hand qty (ties: prefer list order)."""
    best_name: str | None = None
    best_qty = 0
    best_rank = 999
    prefer_rank = {name: i for i, name in enumerate(WAREHOUSE_PREFER)}
    for name, field_name in WAREHOUSE_FIELDS:
        qty = _i(product.get(field_name))
        if qty <= 0:
            qty = _i(product.get(f"Quantity{name}"))
        if qty <= 0:
            continue
        rank = prefer_rank.get(name, 999)
        if qty > best_qty or (qty == best_qty and rank < best_rank):
            best_qty = qty
            best_name = name
            best_rank = rank
    return best_name


@dataclass(frozen=True)
class ShippingQuote:
    """Result of a shipping cost resolution attempt."""

    status: str  # RESOLVED | UNRESOLVED
    cost_cad: float | None
    warehouse: str | None = None
    weight_lb: float = 0.0
    carrier: str | None = None
    method_id: str | None = None
    method_label: str | None = None
    source: str | None = None  # cart_shipping_methods | shipping_label_estimate | injected
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def resolved(self) -> bool:
        return self.status == STATUS_RESOLVED and self.cost_cad is not None

    @classmethod
    def unresolved(
        cls,
        *,
        reason: str,
        warehouse: str | None = None,
        weight_lb: float = 0.0,
        source: str | None = None,
    ) -> "ShippingQuote":
        return cls(
            status=STATUS_UNRESOLVED,
            cost_cad=None,
            warehouse=warehouse,
            weight_lb=weight_lb,
            source=source,
            detail={"reason": reason},
        )


class ShippingQuoteProvider(Protocol):
    def quote_product(
        self,
        product: Mapping[str, Any],
        *,
        ship_to: Mapping[str, str],
    ) -> ShippingQuote: ...


def parse_cart_shipping_methods(payload: Any) -> ShippingQuote:
    """Pick the cheapest method from Cart/ShippingMethods response."""
    methods: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        info = payload.get("ShippingMethods") or payload
        if isinstance(info, dict):
            raw = info.get("Methods") or []
            if isinstance(raw, list):
                methods = [m for m in raw if isinstance(m, dict)]
        elif isinstance(payload.get("Methods"), list):
            methods = [m for m in payload["Methods"] if isinstance(m, dict)]
    elif isinstance(payload, list):
        methods = [m for m in payload if isinstance(m, dict)]

    best: dict[str, Any] | None = None
    best_cost: float | None = None
    for m in methods:
        # Prefer RealShippingCharges when present, else Fees - Discount
        cost = m.get("RealShippingCharges")
        if cost is None:
            try:
                fees = float(m.get("Fees") or 0.0)
                disc = float(m.get("Discount") or 0.0)
                cost = fees - disc
            except (TypeError, ValueError):
                continue
        try:
            cost_f = float(cost)
        except (TypeError, ValueError):
            continue
        if best_cost is None or cost_f < best_cost:
            best_cost = cost_f
            best = m
    if best is None or best_cost is None:
        return ShippingQuote.unresolved(
            reason="no_methods_in_cart_shipping_response",
            source="cart_shipping_methods",
        )
    return ShippingQuote(
        status=STATUS_RESOLVED,
        cost_cad=round(best_cost, 4),
        carrier=str(best.get("Label") or best.get("Description") or "") or None,
        method_id=str(best.get("MethodId") or "") or None,
        method_label=str(best.get("Label") or best.get("Description") or "") or None,
        source="cart_shipping_methods",
        detail={"raw_method_keys": sorted(best.keys())},
    )


def parse_shipvia_estimates(payload: Any) -> ShippingQuote:
    """Pick cheapest ShipViaEstimate / ShippingLabel/Estimate row."""
    rows: list[dict[str, Any]]
    if isinstance(payload, list):
        rows = [r for r in payload if isinstance(r, dict)]
    elif isinstance(payload, dict) and isinstance(payload.get("estimates"), list):
        rows = [r for r in payload["estimates"] if isinstance(r, dict)]
    else:
        return ShippingQuote.unresolved(
            reason="empty_shipvia_estimate_response",
            source="shipping_label_estimate",
        )
    best = None
    best_cost = None
    for r in rows:
        try:
            price = float(r.get("Price"))
        except (TypeError, ValueError):
            continue
        if best_cost is None or price < best_cost:
            best_cost = price
            best = r
    if best is None or best_cost is None:
        return ShippingQuote.unresolved(
            reason="no_priced_carriers",
            source="shipping_label_estimate",
        )
    return ShippingQuote(
        status=STATUS_RESOLVED,
        cost_cad=round(best_cost, 4),
        carrier=str(best.get("Carrier") or best.get("CarrierCode") or "") or None,
        source="shipping_label_estimate",
        detail={"carrier_code": best.get("CarrierCode")},
    )


def compute_landed_cost_with_quote(
    product: Mapping[str, Any],
    quote: ShippingQuote,
) -> tuple[float | None, ShippingQuote]:
    """landed = net_cost + quoted shipping. None landed if quote unresolved."""
    dealer = _f(product.get("dealer_cost"))
    rebate = _f(product.get("rebate"))
    net = _f(product.get("net_cost"))
    if net <= 0:
        net = max(0.0, dealer - rebate)
    if not quote.resolved:
        return None, quote
    assert quote.cost_cad is not None
    return round(net + float(quote.cost_cad), 4), quote


@dataclass
class InjectedQuoteProvider:
    """Test/offline provider: map sku -> cost, else UNRESOLVED."""

    costs: dict[str, float] = field(default_factory=dict)
    default_cost: float | None = None

    def quote_product(
        self,
        product: Mapping[str, Any],
        *,
        ship_to: Mapping[str, str],
    ) -> ShippingQuote:
        _ = ship_to
        sku = str(product.get("sku") or "")
        warehouse = pick_fulfillment_warehouse(product)
        weight = _f(product.get("unit_weight") or product.get("UnitWeight"))
        if sku in self.costs:
            return ShippingQuote(
                status=STATUS_RESOLVED,
                cost_cad=float(self.costs[sku]),
                warehouse=warehouse,
                weight_lb=weight,
                source="injected",
                carrier="injected",
            )
        if self.default_cost is not None:
            return ShippingQuote(
                status=STATUS_RESOLVED,
                cost_cad=float(self.default_cost),
                warehouse=warehouse,
                weight_lb=weight,
                source="injected",
                carrier="injected",
            )
        return ShippingQuote.unresolved(
            reason="no_injected_quote",
            warehouse=warehouse,
            weight_lb=weight,
            source="injected",
        )


@dataclass
class RandmarQuoteProvider:
    """Live read-only quotes via Cart/ShippingMethods and ShippingLabel/Estimate.

    Never calls Cart/Process*. SUPPLIER_ORDERS_ENABLED must stay false.
    """

    client: Any  # RandmarClient
    prefer: Sequence[str] = ("cart_shipping_methods", "shipping_label_estimate")
    cart_prefix: str = "ff-ship-quote"

    def quote_product(
        self,
        product: Mapping[str, Any],
        *,
        ship_to: Mapping[str, str],
    ) -> ShippingQuote:
        sku = str(product.get("sku") or "")
        warehouse = pick_fulfillment_warehouse(product)
        weight = _f(product.get("unit_weight") or product.get("UnitWeight"))
        if not sku:
            return ShippingQuote.unresolved(
                reason="missing_sku",
                warehouse=warehouse,
                weight_lb=weight,
            )
        last = ShippingQuote.unresolved(
            reason="no_quote_source_succeeded",
            warehouse=warehouse,
            weight_lb=weight,
        )
        for source in self.prefer:
            try:
                if source == "cart_shipping_methods":
                    q = self.client.estimate_cart_shipping(
                        sku, ship_to=ship_to, cart_prefix=self.cart_prefix
                    )
                elif source == "shipping_label_estimate":
                    q = self.client.estimate_shipping_label(
                        product, ship_to=ship_to, warehouse=warehouse
                    )
                else:
                    continue
            except Exception as exc:  # noqa: BLE001 — quote failures -> UNRESOLVED
                last = ShippingQuote.unresolved(
                    reason=f"{source}_error:{type(exc).__name__}",
                    warehouse=warehouse,
                    weight_lb=weight,
                    source=source,
                )
                continue
            q = ShippingQuote(
                status=q.status,
                cost_cad=q.cost_cad,
                warehouse=warehouse,
                weight_lb=weight,
                carrier=q.carrier,
                method_id=q.method_id,
                method_label=q.method_label,
                source=q.source,
                detail=dict(q.detail),
            )
            if q.resolved:
                return q
            last = q
        return last

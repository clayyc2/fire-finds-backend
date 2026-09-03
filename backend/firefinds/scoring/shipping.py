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

import math
import time
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

# Randmar ShipToLocation fields required by Cart/ShippingMethods (OpenAPI V4):
# Name, Street1, Street2 (may be empty), City, Province (2-letter CA/US),
# PostalCode, Country (CA or US). Schema marks them nullable but the endpoint
# description requires this subset. additionalProperties=false — do not send extras.
SHIPTO_LOCATION_FIELDS = (
    "Name",
    "Street1",
    "Street2",
    "City",
    "Province",
    "PostalCode",
    "Country",
)

# Representative Canadian destinations for ranking/profitability screening.
# Fulfillment later uses the buyer's actual postal code for the real quote.


@dataclass(frozen=True)
class Destination:
    """A representative ship-to used only for screening quotes."""

    dest_id: str
    city: str
    province: str
    postal_code: str
    street1: str
    country: str = "CA"
    name: str = "Fire Finds Estimate"

    @property
    def label(self) -> str:
        return f"{self.city} {self.province}"


REPRESENTATIVE_DESTINATIONS = (
    Destination(
        dest_id="calgary",
        city="Calgary",
        province="AB",
        postal_code="T2P 1J9",
        street1="101 8 Ave SW",
    ),
    Destination(
        dest_id="vancouver",
        city="Vancouver",
        province="BC",
        postal_code="V6B 1A1",
        street1="555 W Hastings St",
    ),
    Destination(
        dest_id="toronto",
        city="Toronto",
        province="ON",
        postal_code="M5H 2N2",
        street1="100 King St W",
    ),
    Destination(
        dest_id="montreal",
        city="Montreal",
        province="QC",
        postal_code="H3B 1A7",
        street1="800 Rene-Levesque Blvd W",
    ),
    Destination(
        dest_id="halifax",
        city="Halifax",
        province="NS",
        postal_code="B3J 1S9",
        street1="1701 Hollis St",
    ),
)

FULFILLMENT_NOTE = (
    "Representative destinations are used only to screen profitability "
    "(p75 of resolved quotes). Fulfillment will later request a live Randmar "
    "quote for the buyer's actual postal code; that quote is the real shipping "
    "cost at order time."
)


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
    """Test/offline provider: map sku / dest -> cost, else UNRESOLVED."""

    costs: dict[str, float] = field(default_factory=dict)
    default_cost: float | None = None
    dest_costs: dict[str, float] = field(default_factory=dict)

    def _lookup_cost(
        self, sku: str, ship_to: Mapping[str, str]
    ) -> float | None:
        dest_id = str(ship_to.get("dest_id") or "")
        postal = str(ship_to.get("PostalCode") or ship_to.get("postal_code") or "")
        for key in (f"{sku}:{dest_id}", f"{sku}:{postal}", sku):
            if key and key in self.costs:
                return float(self.costs[key])
        for key in (dest_id, postal):
            if key and key in self.dest_costs:
                return float(self.dest_costs[key])
        if self.default_cost is not None:
            return float(self.default_cost)
        return None

    def quote_product(
        self,
        product: Mapping[str, Any],
        *,
        ship_to: Mapping[str, str],
    ) -> ShippingQuote:
        sku = str(product.get("sku") or "")
        warehouse = pick_fulfillment_warehouse(product)
        weight = _f(product.get("unit_weight") or product.get("UnitWeight"))
        cost = self._lookup_cost(sku, ship_to)
        if cost is not None:
            return ShippingQuote(
                status=STATUS_RESOLVED,
                cost_cad=float(cost),
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

    def quote_destinations(
        self,
        product: Mapping[str, Any],
        destinations: Sequence[Destination],
        *,
        sleep_sec: float = 0.0,
    ) -> list["DestinationQuote"]:
        """Quote all dests; reuse one cart for ShippingMethods (never Process)."""
        sku = str(product.get("sku") or "")
        warehouse = pick_fulfillment_warehouse(product)
        weight = _f(product.get("unit_weight") or product.get("UnitWeight"))
        ship_tos = [destination_to_shipto(d) for d in destinations]
        cart_quotes: list[ShippingQuote] | None = None
        if "cart_shipping_methods" in self.prefer and sku:
            try:
                raw = self.client.estimate_cart_shipping_multi(
                    sku,
                    ship_tos=ship_tos,
                    cart_prefix=self.cart_prefix,
                    sleep_sec=sleep_sec,
                )
                cart_quotes = list(raw)
            except Exception as exc:  # noqa: BLE001
                cart_quotes = [
                    ShippingQuote.unresolved(
                        reason=f"cart_shipping_methods_error:{type(exc).__name__}",
                        warehouse=warehouse,
                        weight_lb=weight,
                        source="cart_shipping_methods",
                    )
                    for _ in destinations
                ]
        out: list[DestinationQuote] = []
        for i, dest in enumerate(destinations):
            q: ShippingQuote | None = None
            if cart_quotes is not None and i < len(cart_quotes):
                cq = cart_quotes[i]
                q = ShippingQuote(
                    status=cq.status,
                    cost_cad=cq.cost_cad,
                    warehouse=warehouse,
                    weight_lb=weight,
                    carrier=cq.carrier,
                    method_id=cq.method_id,
                    method_label=cq.method_label,
                    source=cq.source,
                    detail=dict(cq.detail),
                )
            if q is None or not q.resolved:
                if "shipping_label_estimate" in self.prefer:
                    if sleep_sec > 0:
                        time.sleep(sleep_sec)
                    try:
                        lq = self.client.estimate_shipping_label(
                            product,
                            ship_to=destination_to_shipto(dest),
                            warehouse=warehouse,
                        )
                        if lq.resolved:
                            q = ShippingQuote(
                                status=lq.status,
                                cost_cad=lq.cost_cad,
                                warehouse=warehouse,
                                weight_lb=weight,
                                carrier=lq.carrier,
                                method_id=lq.method_id,
                                method_label=lq.method_label,
                                source=lq.source,
                                detail=dict(lq.detail),
                            )
                    except Exception as exc:  # noqa: BLE001
                        q = ShippingQuote.unresolved(
                            reason=f"shipping_label_estimate_error:{type(exc).__name__}",
                            warehouse=warehouse,
                            weight_lb=weight,
                            source="shipping_label_estimate",
                        )
            if q is None:
                q = ShippingQuote.unresolved(
                    reason="no_quote_source_succeeded",
                    warehouse=warehouse,
                    weight_lb=weight,
                )
            out.append(DestinationQuote(destination=dest, quote=q))
        return out


def destination_to_shipto(
    dest: Destination,
    *,
    name: str | None = None,
) -> dict[str, str]:
    """Build a Randmar ShipToLocation payload (only documented fields)."""
    return {
        "Name": name or dest.name,
        "Street1": dest.street1,
        "Street2": "",
        "City": dest.city,
        "Province": dest.province,
        "PostalCode": dest.postal_code,
        "Country": dest.country,
    }


def shipto_for_api(ship_to: Mapping[str, Any]) -> dict[str, str]:
    """Strip extras so ShipToLocation additionalProperties=false is honored."""
    return {
        "Name": str(ship_to.get("Name") or ship_to.get("name") or "Fire Finds Estimate"),
        "Street1": str(ship_to.get("Street1") or ship_to.get("street1") or ""),
        "Street2": str(ship_to.get("Street2") or ship_to.get("street2") or ""),
        "City": str(ship_to.get("City") or ship_to.get("city") or ""),
        "Province": str(ship_to.get("Province") or ship_to.get("province") or ""),
        "PostalCode": str(
            ship_to.get("PostalCode") or ship_to.get("postal_code") or ""
        ),
        "Country": str(ship_to.get("Country") or ship_to.get("country") or "CA"),
    }


def percentile_linear(values: Sequence[float], p: float = 75.0) -> float | None:
    """Inclusive linear-interpolation percentile (numpy 'linear').

    p75 of 5 sorted quotes is the 4th value (index 3). Empty → None.
    Fewer than 5 values still interpolates over whatever resolved.
    """
    xs = sorted(float(v) for v in values)
    if not xs:
        return None
    if len(xs) == 1:
        return round(xs[0], 4)
    if p <= 0:
        return round(xs[0], 4)
    if p >= 100:
        return round(xs[-1], 4)
    k = (len(xs) - 1) * (float(p) / 100.0)
    lo = int(math.floor(k))
    hi = int(math.ceil(k))
    if lo == hi:
        return round(xs[lo], 4)
    w = k - lo
    return round(xs[lo] * (1.0 - w) + xs[hi] * w, 4)


@dataclass(frozen=True)
class DestinationQuote:
    destination: Destination
    quote: ShippingQuote

    @property
    def dest_id(self) -> str:
        return self.destination.dest_id

    @property
    def city(self) -> str:
        return self.destination.city

    @property
    def resolved(self) -> bool:
        return self.quote.resolved


@dataclass(frozen=True)
class MultiDestQuote:
    """Aggregated representative-destination quotes for one SKU.

    shipping_cost_cad is the 75th percentile of *resolved* dest quotes.
    Zero resolved quotes → UNRESOLVED (not finally profitable).
    """

    status: str
    shipping_cost_cad: float | None
    p75_cad: float | None
    quotes: tuple[DestinationQuote, ...]
    resolved_n: int
    unresolved_n: int
    dest_costs: dict[str, float]
    note: str = FULFILLMENT_NOTE

    @property
    def resolved(self) -> bool:
        return self.status == STATUS_RESOLVED and self.shipping_cost_cad is not None

    def as_quote(self) -> ShippingQuote:
        if not self.resolved:
            reasons = [
                dq.quote.detail.get("reason")
                for dq in self.quotes
                if not dq.resolved
            ]
            return ShippingQuote.unresolved(
                reason="zero_resolved_destination_quotes",
                source="multi_dest_p75",
            ) if self.resolved_n == 0 else ShippingQuote.unresolved(
                reason=";".join(str(r) for r in reasons if r) or "unresolved",
                source="multi_dest_p75",
            )
        first = next((dq for dq in self.quotes if dq.resolved), None)
        return ShippingQuote(
            status=STATUS_RESOLVED,
            cost_cad=self.shipping_cost_cad,
            warehouse=first.quote.warehouse if first else None,
            weight_lb=first.quote.weight_lb if first else 0.0,
            carrier=first.quote.carrier if first else None,
            method_id=first.quote.method_id if first else None,
            method_label=first.quote.method_label if first else None,
            source="multi_dest_p75",
            detail={
                "p75_cad": self.p75_cad,
                "resolved_n": self.resolved_n,
                "dest_costs": dict(self.dest_costs),
                "fulfillment_note": FULFILLMENT_NOTE,
            },
        )


def aggregate_destination_quotes(
    dest_quotes: Sequence[DestinationQuote],
) -> MultiDestQuote:
    """p75 over resolved dests; 0 resolved → UNRESOLVED."""
    resolved = [dq for dq in dest_quotes if dq.resolved and dq.quote.cost_cad is not None]
    costs = [float(dq.quote.cost_cad) for dq in resolved]  # type: ignore[arg-type]
    dest_costs = {
        dq.destination.dest_id: float(dq.quote.cost_cad)
        for dq in resolved
        if dq.quote.cost_cad is not None
    }
    p75 = percentile_linear(costs, 75.0)
    if p75 is None:
        status = STATUS_UNRESOLVED
    else:
        status = STATUS_RESOLVED
    return MultiDestQuote(
        status=status,
        shipping_cost_cad=p75,
        p75_cad=p75,
        quotes=tuple(dest_quotes),
        resolved_n=len(resolved),
        unresolved_n=len(dest_quotes) - len(resolved),
        dest_costs=dest_costs,
    )


@dataclass(frozen=True)
class ExpensiveDestFlag:
    fails_expensive_destinations: bool
    failed_cities: tuple[str, ...]
    failed_dest_ids: tuple[str, ...]
    per_dest: tuple[dict[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "fails_expensive_destinations": self.fails_expensive_destinations,
            "failed_expensive_destinations": list(self.failed_cities),
            "failed_dest_ids": list(self.failed_dest_ids),
            "per_dest": list(self.per_dest),
        }


def flag_expensive_destinations(
    dest_costs: Mapping[str, float],
    *,
    sell_price: float,
    net_cost: float,
    rebate: float = 0.0,
    min_profit_cad: float = 8.0,
    min_margin: float = 0.12,
    ebay_fee_rate: float = 0.1325,
    ebay_fee_fixed: float = 0.30,
    dest_id_to_city: Mapping[str, str] | None = None,
) -> ExpensiveDestFlag:
    """Flag dests whose contribution fails $8 / 12% even if p75 passes.

    Does not itself fail p75 profitability — this is a warning flag.
    Unresolved dests are omitted (no cost to evaluate).
    """
    from firefinds.scoring.filters import compute_contribution

    city_map = dict(dest_id_to_city or {})
    if not city_map:
        city_map = {d.dest_id: d.city for d in REPRESENTATIVE_DESTINATIONS}
    per_dest: list[dict[str, Any]] = []
    failed_cities: list[str] = []
    failed_ids: list[str] = []
    for dest_id, cost in dest_costs.items():
        profit, margin, _fees = compute_contribution(
            sell_price,
            net_cost,
            rebate,
            ebay_fee_rate=ebay_fee_rate,
            ebay_fee_fixed=ebay_fee_fixed,
            ship_est_cad=float(cost),
        )
        fail_profit = profit < min_profit_cad
        fail_margin = margin < min_margin
        city = city_map.get(dest_id, dest_id)
        row = {
            "dest_id": dest_id,
            "city": city,
            "cost_cad": round(float(cost), 4),
            "profit_cad": round(float(profit), 4),
            "margin": round(float(margin), 6),
            "fails_profit": fail_profit,
            "fails_margin": fail_margin,
        }
        per_dest.append(row)
        if fail_profit or fail_margin:
            failed_cities.append(city)
            failed_ids.append(dest_id)
    return ExpensiveDestFlag(
        fails_expensive_destinations=bool(failed_cities),
        failed_cities=tuple(failed_cities),
        failed_dest_ids=tuple(failed_ids),
        per_dest=tuple(per_dest),
    )


def quote_representative_destinations(
    provider: ShippingQuoteProvider,
    product: Mapping[str, Any],
    *,
    destinations: Sequence[Destination] | None = None,
    sleep_sec: float = 0.0,
) -> MultiDestQuote:
    """Quote each representative dest and aggregate p75.

    Uses provider.quote_destinations when present (cart reuse).
    """
    dests = tuple(destinations or REPRESENTATIVE_DESTINATIONS)
    quote_many = getattr(provider, "quote_destinations", None)
    dest_quotes: list[DestinationQuote]
    if callable(quote_many):
        dest_quotes = list(quote_many(product, dests, sleep_sec=sleep_sec))
    else:
        dest_quotes = []
        for i, dest in enumerate(dests):
            if i and sleep_sec > 0:
                time.sleep(sleep_sec)
            ship_to = destination_to_shipto(dest)
            # dest_id is for injected providers only; Randmar client strips extras.
            ship_to["dest_id"] = dest.dest_id
            try:
                q = provider.quote_product(product, ship_to=ship_to)
            except Exception as exc:  # noqa: BLE001
                q = ShippingQuote.unresolved(
                    reason=f"provider_error:{type(exc).__name__}",
                    warehouse=pick_fulfillment_warehouse(product),
                )
            dest_quotes.append(DestinationQuote(destination=dest, quote=q))
    return aggregate_destination_quotes(dest_quotes)

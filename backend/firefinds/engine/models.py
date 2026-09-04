from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP

D = Decimal

@dataclass(frozen=True)
class Candidate:
    sku: str; cost: D; shipping: D | None; stock: int
    map_price: D | None = None; competitor_price: D | None = None
    channel_allowed: bool = False; return_risk: bool = False
    demand_score: D = D("0"); competition_score: D = D("0")

@dataclass(frozen=True)
class Decision:
    sku: str; allowed: bool; reason: str
    price: D | None = None; quantity: int = 0; profit: D | None = None
    margin: D | None = None; rank_score: D = D("0")
    gates: tuple[str, ...] = field(default_factory=tuple)

def money(value: D) -> D:
    return value.quantize(D("0.01"), rounding=ROUND_HALF_UP)

"""Six deterministic services with fail-closed live boundaries."""
from __future__ import annotations

import hashlib, json, os, time
from dataclasses import replace
from decimal import ROUND_CEILING, ROUND_FLOOR
from decimal import Decimal as D
from pathlib import Path
from typing import Callable, Iterable, Mapping, Any

from firefinds.config import Settings
from .models import Candidate, Decision, money
from .order_router import OrderRouter
from .storage import checkpoint_lock

class Audit:
    def __init__(self, path: Path): self.path = path
    def write(self, event: str, detail: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = {"ts": time.time(), "event": event, "detail": detail}
        # Private from creation; process-shared append lock and fsync ensure a
        # completed audit call is durable before the next commerce operation.
        with checkpoint_lock(self.path):
            fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as fh:
                os.fchmod(fh.fileno(), 0o600)
                fh.write(json.dumps(row, default=str, sort_keys=True)+"\n")
                fh.flush()
                os.fsync(fh.fileno())

class RandmarImporter:
    def __init__(self, audit: Audit): self.audit = audit
    def normalize(self, rows: Iterable[Mapping[str, Any]]) -> list[Candidate]:
        out = []
        for r in rows:
            sku = str(r["sku"]).strip().upper()
            # Only an explicit boolean true authorizes this channel.
            out.append(Candidate(sku, D(str(r["cost"])), None if r.get("shipping") is None else D(str(r["shipping"])), int(r.get("stock",0)), None if r.get("map") is None else D(str(r["map"])), None if r.get("competitor_price") is None else D(str(r.get("competitor_price"))), r.get("channel_allowed") is True, r.get("return_risk") is not False, D(str(r.get("demand_score",0))), D(str(r.get("competition_score",0)))))
        self.audit.write("randmar_import", {"count": len(out)})
        return out

class OpportunityEngine:
    def __init__(self, settings: Settings): self.s = settings
    def evaluate(self, c: Candidate) -> Decision:
        amounts = (c.cost, c.shipping, c.map_price, c.competitor_price, c.demand_score, c.competition_score)
        if (not c.sku or any(x is not None and (not x.is_finite() or x < 0) for x in amounts)
                or type(c.stock) is not int or c.stock < 0):
            return Decision(c.sku, False, "INVALID_CANDIDATE")
        if self.s.stock_buffer < 0:
            raise ValueError("stock_buffer must be nonnegative")
        gates=[]
        if not c.channel_allowed: gates.append("CHANNEL_PERMISSION")
        if c.shipping is None: gates.append("SHIPPING_UNRESOLVED")
        if c.stock <= self.s.stock_buffer: gates.append("STOCK_BUFFER")
        if c.return_risk: gates.append("RETURN_RISK")
        if gates: return Decision(c.sku, False, gates[0], gates=tuple(gates))
        landed=c.cost+c.shipping
        fee=D(str(self.s.ebay_fee_rate)); fixed=D(str(self.s.ebay_fee_fixed))
        controls = (fee, fixed, D(str(self.s.target_profit_pct)), D(str(self.s.min_contribution_margin)),
                    D(str(self.s.min_contribution_profit_cad)), D(str(self.s.ranking_profit_weight)),
                    D(str(self.s.ranking_demand_weight)), D(str(self.s.ranking_competition_weight)))
        if any(not value.is_finite() or value < 0 for value in controls):
            raise ValueError("economic settings must be finite and nonnegative")
        target=max(D(str(self.s.target_profit_pct)), D(str(self.s.min_contribution_margin)))
        if not D("0") <= fee < 1 or not D("0") <= target < 1-fee:
            raise ValueError("invalid fee/margin configuration")
        floor=max((landed+fixed)/(D("1")-fee-target), (landed+fixed+D(str(self.s.min_contribution_profit_cad)))/(D("1")-fee))
        if c.map_price is not None: floor=max(floor,c.map_price)
        price=floor.quantize(D("0.01"), rounding=ROUND_CEILING)
        if price <= 0:
            return Decision(c.sku, False, "INVALID_PRICE")
        undercut = D(str(self.s.competitor_undercut_cad))
        if not undercut.is_finite() or undercut < D("0.01"):
            raise ValueError("competitor undercut must be at least one cent")
        if c.competitor_price is not None:
            # Caller supplies a verified comparable delivered CAD price on the
            # SAME price basis as this offer. Competition can raise our profit,
            # but can never cut through MAP or either profit minimum.
            competitive = (c.competitor_price-undercut).quantize(D("0.01"), rounding=ROUND_FLOOR)
            price = max(price, competitive)
        profit=money(price*(D("1")-fee)-fixed-landed); margin=profit/price
        if profit < D(str(self.s.min_contribution_profit_cad)) or margin < D(str(self.s.min_contribution_margin)): return Decision(c.sku,False,"PROFIT_FLOOR",price=price,profit=profit,margin=margin)
        score=(profit*D(str(self.s.ranking_profit_weight))+c.demand_score*D(str(self.s.ranking_demand_weight))+c.competition_score*D(str(self.s.ranking_competition_weight)))
        reason = "FLOOR_ABOVE_COMPETITION" if c.competitor_price is not None and price >= c.competitor_price else "PASS"
        return Decision(c.sku,True,reason,price,c.stock-self.s.stock_buffer,profit,margin,score)

class CapacityManager:
    def __init__(self, settings: Settings, live_item_limit: int | None = None, live_value_limit_cad: float | None = None):
        self.s=settings
        self.live_item_limit=live_item_limit
        self.live_value_limit_cad=live_value_limit_cad
    def select(self, decisions: Iterable[Decision], used_items=0, used_value=D("0")) -> list[Decision]:
        def cap(configured, live):
            if live is None:
                return D(str(configured)) if configured > 0 else None
            live = D(str(live))
            return min(D(str(configured)), live) if configured > 0 else live
        items = cap(self.s.monthly_item_limit, self.live_item_limit)
        amount = cap(self.s.monthly_value_limit_cad, self.live_value_limit_cad)
        # Both limits must be known. Explicit zero means zero, never unlimited.
        if items is None or amount is None:
            return []
        headroom = D(str(self.s.capacity_headroom_pct))
        used_value = D(str(used_value))
        if (not items.is_finite() or not amount.is_finite() or
                items < 0 or items != items.to_integral_value() or amount < 0 or
                not D("0") <= headroom < 1 or type(used_items) is not int or
                used_items < 0 or not used_value.is_finite() or used_value < 0):
            raise ValueError("invalid capacity or usage")
        item_cap = max(0, int(items*(1-headroom))-used_items)
        value_cap = max(D("0"), amount*(1-headroom)-used_value)
        if self.s.capacity_policy not in {"balanced", "item_first", "value_first"}:
            raise ValueError("unknown capacity policy")
        candidates = [d for d in decisions if d.allowed and d.price is not None
                      and d.price.is_finite() and d.price > 0 and
                      type(d.quantity) is int and d.quantity > 0]
        if self.s.capacity_policy == "item_first":
            candidates.sort(key=lambda d: (d.price, -d.rank_score, d.sku))
        elif self.s.capacity_policy == "value_first":
            candidates.sort(key=lambda d: (-d.price, -d.rank_score, d.sku))
        else:
            candidates.sort(key=lambda d: (-d.rank_score, d.sku))
        out=[]; seen=set()
        for d in candidates:
            if d.sku in seen:
                continue
            seen.add(d.sku)
            quantity = min(d.quantity, item_cap, int(value_cap // d.price))
            if quantity <= 0:
                continue
            out.append(replace(d, quantity=quantity))
            item_cap -= quantity
            value_cap -= d.price * quantity
        return out

class Repricer:
    def __init__(self, engine: OpportunityEngine): self.engine=engine
    def reprice(self, candidate: Candidate) -> Decision: return self.engine.evaluate(candidate)

class DiscoveryRefreshEngine:
    def __init__(self, importer: RandmarImporter, opportunities: OpportunityEngine, capacity: CapacityManager): self.i=importer; self.o=opportunities; self.c=capacity
    def run(self, rows: Iterable[Mapping[str,Any]]) -> list[Decision]: return self.c.select(self.o.evaluate(x) for x in self.i.normalize(rows))

def retry(operation: Callable[[],Any], attempts: int=5, base_delay=.05) -> Any:
    for n in range(attempts):
        try: return operation()
        except Exception:
            if n+1==attempts: raise
            time.sleep(base_delay*(2**n))

def idempotency_key(*parts: str) -> str: return hashlib.sha256("|".join(parts).encode()).hexdigest()

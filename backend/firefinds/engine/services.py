"""Six deterministic services with fail-closed live boundaries."""
from __future__ import annotations

import hashlib, json, time
from dataclasses import asdict
from decimal import Decimal as D
from pathlib import Path
from typing import Callable, Iterable, Mapping, Any

from firefinds.config import Settings
from .models import Candidate, Decision, money

class Audit:
    def __init__(self, path: Path): self.path = path
    def write(self, event: str, detail: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = {"ts": time.time(), "event": event, "detail": detail}
        with self.path.open("a", encoding="utf-8") as fh: fh.write(json.dumps(row, default=str, sort_keys=True)+"\n")

class RandmarImporter:
    def __init__(self, audit: Audit): self.audit = audit
    def normalize(self, rows: Iterable[Mapping[str, Any]]) -> list[Candidate]:
        out = []
        for r in rows:
            sku = str(r["sku"]).strip().upper()
            out.append(Candidate(sku, D(str(r["cost"])), None if r.get("shipping") is None else D(str(r["shipping"])), int(r.get("stock",0)), None if r.get("map") is None else D(str(r["map"])), None if r.get("competitor_price") is None else D(str(r["competitor_price"])), bool(r.get("channel_allowed",False)), bool(r.get("return_risk",False)), D(str(r.get("demand_score",0))), D(str(r.get("competition_score",0)))))
        self.audit.write("randmar_import", {"count": len(out)})
        return out

class OpportunityEngine:
    def __init__(self, settings: Settings): self.s = settings
    def evaluate(self, c: Candidate) -> Decision:
        gates=[]
        if not c.channel_allowed: gates.append("CHANNEL_PERMISSION")
        if c.shipping is None: gates.append("SHIPPING_UNRESOLVED")
        if c.stock <= self.s.stock_buffer: gates.append("STOCK_BUFFER")
        if c.return_risk: gates.append("RETURN_RISK")
        if gates: return Decision(c.sku, False, gates[0], gates=tuple(gates))
        landed=c.cost+c.shipping
        fee=D(str(self.s.ebay_fee_rate)); fixed=D(str(self.s.ebay_fee_fixed))
        floor=max((landed+fixed)/(D("1")-fee-D(str(self.s.target_profit_pct))), (landed+fixed+D(str(self.s.min_contribution_profit_cad)))/(D("1")-fee))
        if c.map_price is not None: floor=max(floor,c.map_price)
        price=money(floor if c.competitor_price is None else min(max(floor,c.map_price or D("0")),c.competitor_price))
        profit=money(price*(D("1")-fee)-fixed-landed); margin=profit/price
        if profit < D(str(self.s.min_contribution_profit_cad)) or margin < D(str(self.s.min_contribution_margin)): return Decision(c.sku,False,"PROFIT_FLOOR",price=price,profit=profit,margin=margin)
        score=(profit*D(str(self.s.ranking_profit_weight))+c.demand_score*D(str(self.s.ranking_demand_weight))+c.competition_score*D(str(self.s.ranking_competition_weight)))
        return Decision(c.sku,True,"PASS",price,c.stock-self.s.stock_buffer,profit,margin,score)

class CapacityManager:
    def __init__(self, settings: Settings): self.s=settings
    def select(self, decisions: Iterable[Decision], used_items=0, used_value=D("0")) -> list[Decision]:
        item_cap=max(0,int(self.s.monthly_item_limit*(1-self.s.capacity_headroom_pct))-used_items) if self.s.monthly_item_limit else 10**9
        value_cap=D(str(self.s.monthly_value_limit_cad))*(D("1")-D(str(self.s.capacity_headroom_pct)))-used_value if self.s.monthly_value_limit_cad else D("Infinity")
        out=[]; value=D("0")
        for d in sorted((x for x in decisions if x.allowed),key=lambda x:(x.rank_score,x.sku),reverse=True):
            if len(out)>=item_cap or value+(d.price or D("0"))>value_cap: continue
            out.append(d); value+=d.price or D("0")
        return out

class Repricer:
    def __init__(self, engine: OpportunityEngine): self.engine=engine
    def reprice(self, candidate: Candidate) -> Decision: return self.engine.evaluate(candidate)

class OrderRouter:
    def __init__(self, settings: Settings, audit: Audit, checkpoint: Path | None = None):
        self.s=settings; self.audit=audit; self.checkpoint=checkpoint
        self.seen=self._load()
    def _load(self) -> set[str]:
        if not self.checkpoint or not self.checkpoint.is_file(): return set()
        try: return set(json.loads(self.checkpoint.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError): return set()
    def _save(self) -> None:
        if not self.checkpoint: return
        self.checkpoint.parent.mkdir(parents=True, exist_ok=True)
        tmp=self.checkpoint.with_suffix(self.checkpoint.suffix+".tmp")
        tmp.write_text(json.dumps(sorted(self.seen)), encoding="utf-8")
        tmp.replace(self.checkpoint)
    def route(self, order: Mapping[str,Any], submit: Callable[[Mapping[str,Any]],Any]) -> str:
        key=str(order["order_id"])
        if key in self.seen:
            self.audit.write("order_duplicate", {"order_id":key}); return "duplicate"
        if self.s.dry_run or self.s.global_kill_switch or not self.s.supplier_orders_enabled:
            self.audit.write("order_dry_run", {"order_id":key}); return "dry-run"
        result=retry(lambda: submit(order), attempts=self.s.retry_max_attempts)
        self.seen.add(key); self._save()
        self.audit.write("order_submitted", {"order_id":key}); return str(result)

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

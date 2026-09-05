from decimal import Decimal as D
from firefinds.config import Settings
from firefinds.engine.models import Candidate
from firefinds.engine.services import OpportunityEngine, CapacityManager, OrderRouter, Audit

def test_hard_gates_fail_closed():
    d=OpportunityEngine(Settings()).evaluate(Candidate("X",D("10"),None,9))
    assert not d.allowed and "CHANNEL_PERMISSION" in d.gates and "SHIPPING_UNRESOLVED" in d.gates

def test_profit_and_stock_are_deterministic():
    d=OpportunityEngine(Settings(target_profit_pct=.18,stock_buffer=2)).evaluate(Candidate("X",D("20"),D("10"),10,channel_allowed=True))
    assert d.allowed and d.quantity==8 and d.profit >= D("8")

def test_capacity_keeps_headroom():
    s=Settings(monthly_item_limit=2,capacity_headroom_pct=0)
    e=OpportunityEngine(s); ds=[e.evaluate(Candidate(str(i),D("20"),D("10"),10,channel_allowed=True,demand_score=D(i))) for i in range(3)]
    assert len(CapacityManager(s).select(ds))==2

def test_orders_never_submit_by_default(tmp_path):
    called=[]; r=OrderRouter(Settings(),Audit(tmp_path/"audit.jsonl"))
    assert r.route({"order_id":"1"},lambda x: called.append(x))=="dry-run" and not called

def test_order_checkpoint_prevents_replay(tmp_path):
    s=Settings(dry_run=False,global_kill_switch=False,supplier_orders_enabled=True)
    cp=tmp_path/"orders.json"; audit=Audit(tmp_path/"audit.jsonl"); called=[]
    r=OrderRouter(s,audit,cp)
    assert r.route({"order_id":"paid-1"},lambda x: called.append(x) or "R1")=="R1"
    assert OrderRouter(s,audit,cp).route({"order_id":"paid-1"},lambda x: called.append(x))=="duplicate"
    assert len(called)==1

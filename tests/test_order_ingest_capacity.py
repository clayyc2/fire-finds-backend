from decimal import Decimal as D

from firefinds.config import Settings
from firefinds.engine.capacity_live import apply_live_caps, parse_privilege_payload
from firefinds.engine.order_ingest import ROUTED_OFF, dry_run_lifecycle
from firefinds.engine.services import Audit, CapacityManager, OpportunityEngine
from firefinds.engine.models import Candidate


def test_privilege_snapshot_does_not_guess():
    empty = parse_privilege_payload({})
    assert empty.quantity is None and empty.amount_cad is None
    snap = parse_privilege_payload({
        "sellerRegistrationCompleted": False,
        "sellingLimit": {"quantity": 7, "amount": {"value": "250.00", "currency": "CAD"}},
    })
    assert snap.quantity == 7 and snap.amount_cad == D("250.00")
    item, value = apply_live_caps(
        configured_item_limit=0, configured_value_limit_cad=0, snapshot=snap
    )
    assert item == 7 and value == 250.0


def test_capacity_uses_live_item_cap():
    s = Settings(monthly_item_limit=0, capacity_headroom_pct=0)
    e = OpportunityEngine(s)
    ds = [
        e.evaluate(Candidate(str(i), D("20"), D("10"), 10, channel_allowed=True, demand_score=D(i)))
        for i in range(5)
    ]
    picked = CapacityManager(s, live_item_limit=2).select(ds)
    assert len(picked) == 2


def test_ingest_seen_mapped_routed_off(tmp_path):
    s = Settings()
    assert s.supplier_orders_enabled is False
    order = {
        "orderId": "12-345",
        "lineItems": [{"sku": "SKU1", "quantity": 2}],
        "shippingAddress": {
            "fullName": "Buyer",
            "contactAddress": {
                "addressLine1": "1 St",
                "city": "Calgary",
                "stateOrProvince": "AB",
                "postalCode": "T2P1J9",
                "countryCode": "CA",
            },
        },
    }
    report = dry_run_lifecycle(s, Audit(tmp_path / "a.jsonl"), tmp_path / "orders.json", order)
    assert report["state"] == ROUTED_OFF
    assert report["process_called"] is False
    assert report["tracking_posted"] is False
    assert report["publish_called"] is False
    assert report["sku"] == "SKU1"
    assert report["replay"] is True

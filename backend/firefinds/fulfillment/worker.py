"""One-order deterministic workflow; no scheduler or implicit live authorization.

An evidence provider must resolve buyer-specific shipping, channel/return/MAP
policy, and tax/fee-inclusive economics. Missing evidence always holds the order.
No production evidence provider is registered yet. Tests use in-memory adapters.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
import time

from firefinds.engine.models import Candidate
from firefinds.engine.order_ingest import MAPPED, map_ebay_order
from firefinds.engine.order_router import OrderRouter
from firefinds.engine.storage import atomic_json, checkpoint_lock
from .preview import prepare_fulfillment
from .tracking import prepare_tracking
from .tracking_delivery import TrackingDelivery
from .spend_budget import DailySupplierBudget
from .randmar_checkout import cart_name_for
from .supplier_product import parse_supplier_product
from .order_money import parse_order_money


def order_fingerprint(order):
    """Bind evidence to the complete response, including address and discounts.

    A harmless response change can hold an order; it can never loosen a gate.
    The raw buyer response is neither logged nor persisted here.
    """
    return hashlib.sha256(json.dumps(order, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class CheckoutEvidence:
    order_fingerprint: str
    observed_at: float
    supplier: Candidate
    unit_sale_revenue: D
    shipping_method_id: str
    cart: dict = field(repr=False)
    # Explicit policy records, not inferred from a supplier catalog's existence.
    channel_evidence: str = ""
    returns_evidence: str = ""
    map_evidence: str = ""
    shipping_service_evidence: str = ""
    economics_evidence: str = ""
    opportunity_only: bool = True
    currency: str = ""
    # Complete order-level costs, including nonrecoverable taxes, shipping,
    # reserves and maximum platform fees; collected sales tax is NOT revenue.
    total_landed_cost: D | None = None
    total_fee_upper_bound: D | None = None
    catalog_observed_at: float | None = None
    supplier_charge_upper_bound_cad: D | None = None
    # Full fresh Product response: actual cart projections omit purchase flags.
    supplier_product: dict | None = field(default=None, repr=False)


class FulfillmentWorker:
    def __init__(self, *, settings, ebay, supplier, audit, state_dir: Path,
                 sku_mapping: dict, carrier_mapping: dict, clock=time.time):
        if settings.ebay_env not in {"sandbox", "production"}:
            raise ValueError("Explicit supported eBay environment required")
        self.s, self.ebay, self.supplier, self.audit = settings, ebay, supplier, audit
        self.root = Path(state_dir)
        self.mapping, self.carriers, self.clock = dict(sku_mapping), dict(carrier_mapping), clock
        self.router = OrderRouter(settings, audit, self.root / "submissions.json")
        self.tracking = TrackingDelivery(settings, audit, self.root / "tracking.json")
        self.budget = DailySupplierBudget(settings, self.root / "supplier_spend.json", clock)

    def _result(self, oid, state, reason):
        result = {"order_id": oid, "state": state, "reason": reason}
        self.audit.write("fulfillment_worker", result)
        return result

    def run_order(self, order_id, evidence_provider=None):
        if not isinstance(order_id, str) or not order_id.strip():
            raise ValueError("Explicit order ID required")
        # Across processes on this runner: only one full workflow per order.
        lock = self.root / (hashlib.sha256(order_id.encode()).hexdigest() + ".workflow")
        with checkpoint_lock(lock):
            try:
                return self._run(order_id, evidence_provider)
            except Exception as exc:
                # Never include HTTP error bodies, credentials, or buyer data.
                return self._result(order_id, "HELD", "operation_failed:" + type(exc).__name__)

    def _run(self, oid, evidence_provider):
        order = self.ebay.get_order(oid)
        if not isinstance(order, dict) or order.get("orderId") != oid:
            return self._result(oid, "HELD", "order_identity_mismatch")
        submitted = self.router._load().get(oid)
        if submitted:
            return self._resume(oid, order, submitted)
        cancel = order.get("cancelStatus")
        if not isinstance(cancel, dict) or cancel.get("cancelState") != "NONE_REQUESTED":
            return self._result(oid, "HELD", "cancellation_status_unresolved")
        record = map_ebay_order(order)
        if record.state != MAPPED:
            return self._result(oid, "HELD", record.reason)
        if record.sku not in self.mapping:
            return self._result(oid, "HELD", "unverified_supplier_mapping")
        if evidence_provider is None:
            return self._result(oid, "HELD", "buyer_quote_and_policy_evidence_required")
        evidence = evidence_provider(order)
        reason = self._validate_evidence(order, record, evidence)
        if reason:
            return self._result(oid, "HELD", reason)
        preview = prepare_fulfillment(
            settings=self.s, order=order, sku_mapping=self.mapping, supplier=evidence.supplier,
            shipping_method_id=evidence.shipping_method_id,
            unit_sale_revenue=evidence.unit_sale_revenue, quote_observed_at=evidence.observed_at,
            now=self.clock())
        if not preview.allowed:
            return self._result(oid, "HELD", preview.reason)
        if self.s.dry_run or self.s.global_kill_switch or not self.s.supplier_orders_enabled:
            return self._result(oid, "DRY_RUN_READY", "supplier_submission_disabled")
        # Randmar's actual not-found response contract is not yet verified.
        # Never interpret {}, None, or any HTTP failure as proof no PO exists.
        existing = self.supplier.get_order_by_po(oid)
        if existing is not None:
            return self._result(oid, "HELD", "existing_or_unresolved_supplier_po")
        # None is accepted ONLY from an adapter explicitly verifying the
        # supplier's not-found contract, not the inherited HTTP client.
        if getattr(self.supplier, "verified_po_absence_contract", False) is not True:
            return self._result(oid, "HELD", "supplier_po_absence_contract_unverified")
        refreshed = self.ebay.get_order(oid)
        if order_fingerprint(refreshed) != evidence.order_fingerprint:
            return self._result(oid, "HELD", "order_changed_before_submission")
        # A fresh cart GET catches quantity/cost drift after the quote.
        fresh_cart = self.supplier.cart_get(cart_name_for(oid))
        if fresh_cart != evidence.cart:
            return self._result(oid, "HELD", "cart_changed_before_submission")
        if self._validate_evidence(refreshed, record, evidence):
            return self._result(oid, "HELD", "evidence_expired_before_submission")
        facts = {"supplier_sku": preview.supplier_sku, "merchant_sku": record.sku,
                 "quantity": record.qty, "line_item_id": order["lineItems"][0]["lineItemId"]}
        atomic_json(self.root / (hashlib.sha256(oid.encode()).hexdigest() + ".facts.json"), facts)
        def guarded_purchase():
            result = self.router.route({"order_id": oid},
                lambda _: self.supplier.process_cart(cart_name_for(oid), preview.payload))
            if self.router._load().get(oid, {}).get("state") != "SUBMITTED":
                # A guard refusal or unknown outcome must NOT settle the cash
                # reservation and release its carry-forward protection.
                raise RuntimeError("Supplier submission remains unconfirmed")
            return result
        spending = self.budget.execute(oid, evidence.supplier_charge_upper_bound_cad, guarded_purchase)
        if not spending["allowed"]:
            return self._result(oid, "HELD", spending["reason"])
        return self._resume(oid, refreshed, self.router._load()[oid])

    def _validate_evidence(self, order, record, evidence):
        if not isinstance(evidence, CheckoutEvidence):
            return "missing_checkout_evidence"
        if evidence.order_fingerprint != order_fingerprint(order):
            return "evidence_order_mismatch"
        age = D(str(self.clock())) - D(str(evidence.observed_at))
        if not age.is_finite() or not D(0) <= age <= 300:
            return "stale_checkout_evidence"
        if evidence.catalog_observed_at is None:
            return "catalog_freshness_unresolved"
        catalog_age = D(str(self.clock())) - D(str(evidence.catalog_observed_at))
        if not catalog_age.is_finite() or not D(0) <= catalog_age <= 300:
            return "stale_supplier_stock"
        if any(not isinstance(v, str) or not v.strip() for v in (
                evidence.channel_evidence, evidence.returns_evidence, evidence.map_evidence,
                evidence.shipping_service_evidence, evidence.economics_evidence)):
            return "unresolved_policy_shipping_or_economics"
        if evidence.opportunity_only is not False:
            return "opportunity_only_purchase_held"
        if evidence.currency != "CAD" or record.ship_to["Country"].upper() != "CA":
            return "currency_or_destination_not_supported"
        lines = order.get("lineItems", [])
        if not lines[0].get("lineItemId"):
            return "missing_line_item_id"
        candidate = evidence.supplier
        if candidate.sku != self.mapping[record.sku] or candidate.map_price is None:
            return "supplier_or_map_unresolved"
        try:
            product = parse_supplier_product(evidence.supplier_product, candidate.sku)
        except ValueError:
            return "supplier_product_purchase_evidence_unresolved"
        if (product.cost != candidate.cost or product.map_price != candidate.map_price or
                type(candidate.stock) is not int or not 0 <= candidate.stock <= product.stock):
            return "supplier_product_cost_map_or_stock_mismatch"
        cart = evidence.cart
        if not isinstance(cart, dict) or cart.get("Name") != cart_name_for(record.ebay_order_id):
            return "cart_identity_mismatch"
        parts = cart.get("PartNumbers")
        if not isinstance(parts, list) or len(parts) != 1 or not isinstance(parts[0], dict):
            return "cart_must_contain_exact_order_line"
        part = parts[0]
        if (("AvailableToBuy" in part and part["AvailableToBuy"] is not True) or
                ("OpportunityOnly" in part and part["OpportunityOnly"] is not False)):
            return "cart_purchase_permission_unresolved"
        info = part.get("Cart")
        if (not isinstance(info, dict) or part.get("RandmarSKU") != candidate.sku or
                type(info.get("Quantity")) is not int or info["Quantity"] != record.qty or
                D(str(info.get("Price"))) != candidate.cost):
            return "cart_line_cost_or_quantity_mismatch"
        values = (evidence.unit_sale_revenue, evidence.total_landed_cost, evidence.total_fee_upper_bound)
        if any(not isinstance(v, D) or not v.is_finite() or v < 0 for v in values):
            return "incomplete_order_costs"
        try:
            paid = parse_order_money(order)
        except ValueError:
            return "order_money_unresolved"
        if paid.unit_revenue != evidence.unit_sale_revenue:
            return "sale_revenue_evidence_mismatch"
        if paid.unit_item_price < candidate.map_price:
            return "item_price_below_map"
        revenue = paid.revenue
        if revenue <= 0 or candidate.shipping is None:
            return "incomplete_order_costs"
        if evidence.total_landed_cost < (candidate.cost + candidate.shipping) * record.qty:
            return "landed_cost_understated"
        cash = evidence.supplier_charge_upper_bound_cad
        if (not isinstance(cash, D) or not cash.is_finite() or
                cash < (candidate.cost + candidate.shipping) * record.qty or cash <= 0):
            return "supplier_cash_upper_bound_unresolved"
        minimum_fees = max(paid.accrued_marketplace_fees,
            paid.fee_basis * D(str(self.s.ebay_fee_rate)) + D(str(self.s.ebay_fee_fixed)))
        if evidence.total_fee_upper_bound < minimum_fees:
            return "fees_understated"
        profit = revenue - evidence.total_landed_cost - evidence.total_fee_upper_bound
        target = max(D(str(self.s.target_profit_pct)), D(str(self.s.min_contribution_margin)))
        if profit < D(str(self.s.min_contribution_profit_cad)) or profit / revenue < target:
            return "complete_order_profit_floor"
        return None

    def _resume(self, oid, order, submitted):
        facts_path = self.root / (hashlib.sha256(oid.encode()).hexdigest() + ".facts.json")
        if not facts_path.is_file():
            return self._result(oid, "HELD", "missing_submission_facts")
        facts = json.loads(facts_path.read_text())
        cancel = order.get("cancelStatus")
        if not isinstance(cancel, dict) or cancel.get("cancelState") != "NONE_REQUESTED":
            return self._result(oid, "HELD", "purchased_order_cancellation_needs_review")
        lines = order.get("lineItems")
        if (not isinstance(lines, list) or len(lines) != 1 or
                lines[0].get("sku") != facts["merchant_sku"] or
                lines[0].get("lineItemId") != facts["line_item_id"] or
                lines[0].get("quantity") != facts["quantity"]):
            return self._result(oid, "HELD", "purchased_order_line_changed")
        if submitted["state"] != "SUBMITTED":
            doc = self.supplier.get_order_by_po(oid)
            details = doc.get("OrderDetails") if isinstance(doc, dict) else None
            if (not isinstance(details, list) or len(details) != 1 or
                    details[0].get("RandmarSKU") != facts["supplier_sku"] or
                    D(str(details[0].get("QuantityOrdered"))) != facts["quantity"]):
                return self._result(oid, "HELD", "supplier_reconciliation_required")
            outcome = self.router.reconcile(oid, lambda _: doc)
            if outcome != "reconciled":
                return self._result(oid, "HELD", "supplier_reconciliation_required")
            submitted = self.router._load()[oid]
        self.budget.confirm(oid)
        prepared = prepare_tracking(order=order, supplier_sku=facts["supplier_sku"],
                                    supplier_order_number=submitted.get("supplier_order_number"),
                                    shipments=self.supplier.list_shipments(), carrier_mapping=self.carriers)
        if not prepared["prepared"]:
            return self._result(oid, "AWAITING_SHIPMENT", prepared["reason"])
        outcome = self.tracking.deliver(oid, prepared["payload"], self.ebay)
        return self._result(oid, "FULFILLED" if outcome == "confirmed" else "TRACKING_HELD", outcome)

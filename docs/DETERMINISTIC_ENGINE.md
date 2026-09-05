# Deterministic engine architecture

AI is not on the execution path. Live writes stay gated off.

1. Randmar Importer
2. Opportunity Engine (fail-closed gates)
3. Capacity Manager (privilege fixture or live GET; never guess)
4. Repricer
5. Order Router: ingest plus connected fulfillment worker (eBay orderId = Randmar PO)
6. Discovery/Refresh

## Simulated E2E
`firefinds simulated-e2e` using tests/fixtures/{randmar_catalog_mini,ebay_privilege,ebay_paid_order}.json

Live Sandbox GETs independently passed on this local clone on 2026-09-05
(privilege, orders, policies, inventory locations, payments program). The account returned
`sellerRegistrationCompleted=false` and no numeric selling limit, so Capacity
Manager remains fail-closed instead of guessing Sandbox capacity. Production
reads separately returned limits of 5,000 items / CAD 69,515.02 and matched all
48 roster entries to published offers. Write gates remain off; actual remaining
capacity and supplier economics still require verification. Grok is retired from
execution; see `CODEX_TAKEOVER.md` for migration and evidence details.

## Current execution boundaries

`poll-sandbox-orders --mapping data/verified_sku_mapping.json` performs a bounded
read-only sweep and persists order records privately. The mapping file is a JSON
object of exact merchant SKU to verified Randmar SKU; unknown matches are held.
`fulfillment.preview.prepare_fulfillment` accepts an explicit supplier mapping,
fresh buyer-destination quote and net per-unit sale revenue (CAD, after discounts,
excluding tax). It prepares checkout fields only. The caller is responsible for
collecting/normalizing this source evidence. A connected worker now consumes
explicit evidence, but no production evidence collector is registered yet.

The submission guard durably records `SUBMITTING` before one callback attempt.
Timeouts become `UNKNOWN`; crashes leave `SUBMITTING`. Both remain held across
restart and can only be marked submitted after a matching supplier PO/order read.
Empty lookup evidence never authorizes a second purchase. All cooperating workers
must use the same checkpoint/lock path on a POSIX filesystem; multiple independent
runner stores are not a supported deployment. The guard is not a substitute for
catalog, economics, payment and channel checks before purchase.

Capacity limits apply to units and total quantity times price. Unknown item or
value caps hold allocation. `balanced` prioritizes rank score, `item_first` low
unit price, and `value_first` high unit price. Cross-worker capacity reservations
and current account-usage collection remain to be connected before publishing.

The CLI fixture lifecycle covers catalog → score → capacity → ingest. The
connected fulfillment worker now joins refreshed paid-order evidence, cart and
economics checks, guarded submission, shipment reads and durable tracking
delivery. Tests use fake commerce adapters and cover timeout/crash recovery;
no simulation claims an actual purchase or shipment. A read-only production
order sweep is available without enabling writes. See `FULFILLMENT_WORKER.md`
for the implementation boundary, evidence and remaining launch checklist.

## Evidence boundary for demand discovery

`EBAY_DEMAND_FIRST` accepts only attributable demand observations and uses exact
UPC or controlled MPN/manufacturer matching. The standard Browse API is not a
general sold-history feed. Until an approved official sold-history source is
available, the production provider must remain empty/provisional rather than
fabricating sold counts. Randmar-first ranking and all economic gates continue
to operate deterministically without AI.

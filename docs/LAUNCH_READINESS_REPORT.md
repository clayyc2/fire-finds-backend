# Launch readiness report (updated 2026-09-05)

**Overall:** `NOT_READY_FOR_LIVE__LOCAL_FAILURE_TESTS_PASS`

Live-write gates remain OFF. The encrypted Grok handoff has now been verified
and reviewed locally; environment-matched credentials are installed privately.
Independent Sandbox AND Production read-only account checks passed here on
2026-09-05. Production roster reconciliation matched 48/48 published offers.
No publish, fulfillment write, or supplier order was performed during this
verification. Grok/Grok Bots are retired from Fire Finds execution.

## Implemented
- Six deterministic service components; continuous production operation is not wired or deployed.
- Order ingest: `SEEN → MAPPED → ROUTED_OFF` (or `BLOCKED`).
- Capacity metadata from privilege fixtures. Missing payload is not guessed.
- Simulated E2E: catalog → score → cap select → ingest → performance record. No ProcessNew / publish / tracking POST.
- Randmar V4 AddItem + ShippingMethods previously passed live; ProcessNew never called.
- Durable submission intent is stored before a purchase callback. Concurrent
  workers are locked; timeout/crash outcomes require exact-PO reconciliation
  and never automatically re-enter the purchase path.
- Single-line ingest rejects unpaid, cancelled, already-started, malformed and
  zero/fractional-quantity orders. Multi-line orders are explicitly held.
- `poll-sandbox-orders` connects paginated eBay reads to protected checkpoints,
  requiring an explicit merchant-SKU to Randmar-SKU mapping file. Partial or
  failed sweeps never report completion. No submitter is attached.
- Fulfillment preview checks mapping, quote freshness, stock buffer, channel,
  return risk, safe sale price, and checkout fields, preparing a private payload.
- Tracking preparation requires exact eBay PO, Randmar order number, supplier
  SKU, full shipped quantity and an explicit carrier mapping. Missing/ambiguous
  or partial shipment evidence is held; it never posts a tracking update.
- A connected single-line fulfillment worker now coordinates fresh order/cart
  checks, explicit policy/economics evidence, supplier submission, shipment
  matching and durable tracking delivery. Tested with in-memory adapters only;
  no production quote/economics provider or live-write CLI is registered.
- A protected real-account order sweep feeds the worker using read-only clients.
  Dry-run and the global kill switch now guard old Sandbox listing-write paths
  too, even when valid credentials are installed.
- Capacity counts units and price times units, preserves headroom/used capacity,
  handles explicit zero, and refuses allocation if either cap is unknown.
  Configured caps support planning, not proof of actual account limits.
- Pricing preserves MAP and both profit floors, then keeps competitive upside:
  default C$0.01 below a verified comparable offer when that is above the floor.
  If competitors are cheaper, the safe floor wins. See `OPERATING_POLICY.md`.
- Shared supplier-cash reservations enforce C$2,500/day (America/Edmonton),
  including in-flight/uncertain charges. Restarts cannot reset the allowance;
  concurrency and midnight/uncertainty behavior are covered by tests.
- Bounded eBay GET retries honor Retry-After up to 60 seconds; longer delays
  stop the sweep for a later invocation. No 429/5xx POST retry was added.

## Connected to live APIs
- Randmar account / AddItem / ShippingMethods (earlier probe).
- eBay Browse / Sandbox Inventory+Offer on other hosts (publish refused).
- eBay Sandbox user OAuth with a renewable refresh token stored outside Git
  using mode `600` permissions.
- Read-only Sandbox privilege, order, policy, inventory-location, and payments
  program checks.

## Still simulated
- Nonempty paid-order fulfillment, supplier acceptance and shipment delivery.
- Capacity allocation/usage reservations (real limit GETs are separately verified).
- Tracking writes and confirmation, including timeout/crash recovery.

## Independently verified Sandbox account facts (2026-09-05)
- `sellerRegistrationCompleted=false`.
- `sellingLimit=null`; Capacity Manager records this as unavailable and does not
  guess a limit.
- Payments program is `OPTED_IN` for `EBAY_CA`.
- Exactly one payment, return, and fulfillment policy was returned.
- Inventory location `firefinds_laval_wh` exists.
- Orders returned: `0`.
- Local sanitized report: `data/verification-20260905-sandbox/account_readiness.json`.

## Independently verified Production facts (2026-09-05)
- Seller registration completed; limits 5,000 items and CAD 69,515.02.
- Account privilege, orders, policies, locations and payments reads all passed.
- 48/48 roster listing IDs matched published offers; zero recent orders returned.
- Local evidence: `data/verification-20260905-production-correct-host/`.
- Remaining monthly capacity and current supplier economics are not yet verified.
- Fresh Randmar catalog: 19,583 rows. Exact supplier-product identity verified
  for all 48 listings against live eBay inventory/offer reads. No below-MAP or
  stock-buffer violation appeared in the snapshot. Buyer-specific delivery
  economics and channel permission are NOT implied by those checks.
- `HPW2020XC` remains held for automatic purchasing because Randmar marks it
  opportunity-only; the existing listing was not modified.
- The new connected read-only order sweep returned zero recent orders.
  Evidence and interpretation: `FULFILLMENT_WORKER.md`.

## Test status
334 tests passed locally, including failure and concurrency tests. Connected
worker tests cover purchase/tracking acceptance followed by timeout, crash
reconciliation, changed payment/cart/line data, stale stock and quotes, missing
policy/economics, conflicting manual tracking and no automatic resubmission.
They use in-memory commerce adapters, not real supplier purchases. The actual
`python3 -m firefinds.cli.main simulated-e2e` command also passed without network
writes. Tracking is explicitly unprepared because shipment evidence is absent.
This is not a full supplier-order-to-eBay-tracking E2E pass.

## Queues (freeze `20260904_1348`)
RANDMAR_FIRST SAFE 127 / DEST 25 / QUAR 85 / ranked 152. EBAY_DEMAND_FIRST scaffold.

## Remaining blockers
1. Secure migration and local account reads are complete. Review remaining
   inherited code/assets and supplier credentials without resuming Grok/Bots.
2. Investigate `sellerRegistrationCompleted=false`; it is not established as
   the only blocker, and successful offer creation does not establish readiness.
3. Product identity and catalog availability are checked for 48/48. Resolve
   channel/return evidence and buyer-specific shipping/economics, including the
   contractual/opportunity-only HP item, before any purchase.
4. Connect the tested worker to a verified production evidence provider and
   supplier PO-absence/carrier contracts. Tests do not prove a deployed worker.
5. Add multi-line/partial-shipment handling, shipment reconciliation, account
   usage reservations, stale-limit checks, scheduling and operational alerts.
6. Prove the real Sandbox paid-order/tracking lifecycle under the permitted
   test scope. Simulated output is not evidence of a purchase or shipment.
7. Validate live inventory economics/channel evidence and the demand source;
   separately review a controlled supplier test. Clay has conditionally approved
   automatic activation once readiness is proven under `OPERATING_POLICY.md`.
   Existing live listings continue to require manual fulfillment.

## Gates that stay false
LIVE_LISTINGS_ENABLED, EBAY_SANDBOX_PUBLISH_ENABLED, EBAY_PRODUCTION_ENABLED, EBAY_TRACKING_UPDATES_ENABLED, SUPPLIER_ORDERS_ENABLED

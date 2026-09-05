# Launch readiness report (updated 2026-09-05)

**Overall:** `SANDBOX_READS_GREEN__LIVE_WRITES_LOCKED`

Live-write gates remain OFF. Sandbox OAuth and the read-only account checks were
completed on 2026-09-05; no publish, fulfillment write, or supplier order was
performed.

## Implemented
- Six deterministic modules.
- Order ingest: `SEEN → MAPPED → ROUTED_OFF` (or `BLOCKED`).
- Capacity metadata from privilege fixtures. Missing payload is not guessed.
- Simulated E2E: catalog → score → cap select → ingest → performance record. No ProcessNew / publish / tracking POST.
- Randmar V4 AddItem + ShippingMethods previously passed live; ProcessNew never called.

## Connected to live APIs
- Randmar account / AddItem / ShippingMethods (earlier probe).
- eBay Browse / Sandbox Inventory+Offer on other hosts (publish refused).
- eBay Sandbox user OAuth with a renewable refresh token stored outside Git
  using mode `600` permissions.
- Read-only Sandbox privilege, order, policy, inventory-location, and payments
  program checks.

## Still simulated
- Paid-order ingest and fulfillment.
- Capacity caps from fixture (`quantity=25`, `amount=5000 CAD`).
- Tracking payload preparation.

## Verified Sandbox account facts (2026-09-05)
- `sellerRegistrationCompleted=false`.
- `sellingLimit=null`; Capacity Manager records this as unavailable and does not
  guess a limit.
- Payments program is `OPTED_IN` for `EBAY_CA`.
- Exactly one payment, return, and fulfillment policy was returned.
- Inventory location `firefinds_laval_wh` exists.
- Orders returned: `0`.
- Sanitized runner report: `data/reports/sandbox_readonly_checks_latest.md`
  (runner-local; no credentials belong in Git).

## Test status
184 passed on this runner after simulated E2E.

## Queues (freeze `20260904_1348`)
RANDMAR_FIRST SAFE 127 / DEST 25 / QUAR 85 / ranked 152. EBAY_DEMAND_FIRST scaffold.

## Remaining blockers
1. Complete the eBay Sandbox test seller registration flow so the privilege API
   returns `sellerRegistrationCompleted=true`.
2. A real Sandbox paid-order lifecycle still requires a separately authorized
   Sandbox publish and test-buyer checkout. Until then, order ingest remains
   fixture-verified only.
3. Complete the no-write lifecycle with a real Sandbox paid order, then record
   the result and rerun the complete test suite.
4. Clay signature is required before any live write. Production access and
   supplier-order submission remain separate approvals.

## Gates that stay false
LIVE_LISTINGS_ENABLED, EBAY_SANDBOX_PUBLISH_ENABLED, EBAY_PRODUCTION_ENABLED, EBAY_TRACKING_UPDATES_ENABLED, SUPPLIER_ORDERS_ENABLED

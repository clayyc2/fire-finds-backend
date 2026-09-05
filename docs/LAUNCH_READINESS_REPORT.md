# Launch readiness report (updated 2026-09-05)

**Overall:** `NOT_READY_FOR_LIVE`

Live-write gates remain OFF. Live Sandbox GET probes are pending credentials.

## Implemented
- Six deterministic modules.
- Order ingest: `SEEN → MAPPED → ROUTED_OFF` (or `BLOCKED`).
- Capacity metadata from privilege fixtures. Missing payload is not guessed.
- Simulated E2E: catalog → score → cap select → ingest → performance record. No ProcessNew / publish / tracking POST.
- Randmar V4 AddItem + ShippingMethods previously passed live; ProcessNew never called.

## Connected to live APIs
- Randmar account / AddItem / ShippingMethods (earlier probe).
- eBay Browse / Sandbox Inventory+Offer on other hosts (publish refused).

## Still simulated
- Paid-order ingest and fulfillment.
- Capacity caps from fixture (`quantity=25`, `amount=5000 CAD`).
- Tracking payload preparation.

## Pending (secret-dependent, not failed)
- GET privilege, orders, three policies, inventory locations, payments program.

## Test status
184 passed on this runner after simulated E2E.

## Queues (freeze `20260904_1348`)
RANDMAR_FIRST SAFE 127 / DEST 25 / QUAR 85 / ranked 152. EBAY_DEMAND_FIRST scaffold.

## Remaining blockers
1. Sandbox Client Secret + refresh token in runner secret store.
2. `firefinds ebay-sandbox-reads` then persist real sellingLimit.
3. Clay signature before any live write.

## Gates that stay false
LIVE_LISTINGS_ENABLED, EBAY_SANDBOX_PUBLISH_ENABLED, EBAY_PRODUCTION_ENABLED, EBAY_TRACKING_UPDATES_ENABLED, SUPPLIER_ORDERS_ENABLED

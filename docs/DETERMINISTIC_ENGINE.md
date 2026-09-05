# Deterministic engine architecture

AI is not on the execution path. Live writes stay gated off.

1. Randmar Importer
2. Opportunity Engine (fail-closed gates)
3. Capacity Manager (privilege fixture or live GET; never guess)
4. Repricer
5. Order ingest `SEEN → MAPPED → ROUTED_OFF` (eBay orderId = Randmar PO)
6. Discovery/Refresh

## Simulated E2E
`firefinds simulated-e2e` using tests/fixtures/{randmar_catalog_mini,ebay_privilege,ebay_paid_order}.json

Live Sandbox GETs: verified 2026-09-05 (privilege, orders, policies, inventory
locations, payments program). The account reported
`sellerRegistrationCompleted=false` and no numeric selling limit, so Capacity
Manager remains fail-closed instead of guessing capacity. Write gates: off.

## Evidence boundary for demand discovery

`EBAY_DEMAND_FIRST` accepts only attributable demand observations and uses exact
UPC or controlled MPN/manufacturer matching. The standard Browse API is not a
general sold-history feed. Until an approved official sold-history source is
available, the production provider must remain empty/provisional rather than
fabricating sold counts. Randmar-first ranking and all economic gates continue
to operate deterministically without AI.

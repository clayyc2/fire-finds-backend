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

Live Sandbox GETs: pending credentials. Write gates: off.

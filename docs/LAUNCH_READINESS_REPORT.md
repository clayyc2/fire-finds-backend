# Launch readiness report (updated 20260905_0130)

Generated: `2026-09-05`
**Overall:** `NOT_READY_FOR_LIVE` (Sandbox Offer unblocked; order lifecycle incomplete)

**Publish / supplier orders: OFF** — next irreversible step needs Clay go-live signature.

## Authoritative freeze
| Metric | Value |
|--------|------:|
| Snapshot | `20260904_1348` |
| SAFE_NATIONWIDE | **127** |
| DESTINATION_SENSITIVE | **25** |
| QUARANTINE_UNRESOLVED | **85** |
| Listable / ranked | **152 / 152** |

## Pass/fail matrix (delta)
| Item | Status | Evidence |
|------|:------:|----------|
| Sandbox Inventory Final 5 | **PASS 5/5** | `sandbox_inventory_offer_e2e_20260904T201135Z` |
| Sandbox Offer Final 5 | **PASS 5/5** | same — real policy IDs `6248961000`/`6248962000`/`6248963000` |
| Publish refuse | **PASS 5/5** | `EBAY_SANDBOX_PUBLISH_ENABLED=false` |
| Business Policies | **PASS** | Account API `opt_in` `SELLING_POLICY_MANAGEMENT` + create policies (sandbox web sign-in broken) |
| sellerRegistrationCompleted | **false** (non-blocking for Offer) | privilege still false; Offer succeeded anyway |
| Sandbox web UI sign-in | **BROKEN** | `signin.sandbox.ebay.com` 403/Akamai; `sandbox.ebay.com` → splash challenge — use API path |
| Randmar OAuth/account read | **PASS** | Dedicated `Fire Finds Order Router` client; authenticated V4 account request returned 200 |
| Randmar cart AddItem | **PASS** | Marked no-purchase probe returned 200/`true` |
| Randmar shipping quote | **PASS** | Probe cart returned 200 and supported carrier method IDs |
| Randmar `ProcessNew` | **NOT RUN** | Intentionally hard-gated; no supplier order or payment created |
| Randmar PO dedupe/tracking | **PENDING E2E** | Client methods implemented; authenticated lifecycle evidence still required |
| eBay paid-order ingest/fulfillment | **IMPLEMENTED; PENDING E2E** | Official order, privilege, policy, location, payment-program, existing-fulfillment, and tracking wrappers added; tracking defaults OFF |

## Clay-only remaining
1. Complete the no-purchase Randmar PO lookup and shipment-read probes.
2. Run read-only eBay Sandbox probes for privileges, empty orders, policies,
   locations, existing fulfillments, and payments status.
3. Complete eBay Sandbox paid-order ingest, supplier-order simulation, tracking,
   fulfillment update, duplicate replay, retry, and checkpoint-resume tests.
4. Re-run the full unit suite in a clean environment.
5. **Explicit go-live authorization** before any production publish or supplier
   order — sign `docs/CLAY_GO_LIVE_AUTHORIZATION_BRIEF.md` only after the lifecycle
   above passes.
6. Optional: Production keys-page visual confirm if still desired (API Browse already PASS).
7. Sandbox website seller registration remains blocked by eBay SORRY/Akamai —
   **not required** for Offer E2E anymore.

## Do not
- Flip publish/orders gates without Clay signature
- Place supplier Process orders

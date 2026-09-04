# Launch readiness report (updated 20260904_2012)

Generated: `2026-09-04T20:12:01.749554+00:00`
**Overall:** `READY_FOR_CLAY_AUTH` (Sandbox Offer **unblocked**)

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

## Clay-only remaining
1. **Explicit go-live authorization** before any publish/orders — sign `docs/CLAY_GO_LIVE_AUTHORIZATION_BRIEF.md` (Phase A/B sandbox publish optional; Phase C production live).
2. Optional: Production keys-page visual confirm if still desired (API Browse already PASS).
3. Sandbox website seller registration still blocked by eBay SORRY/Akamai — **not required** for Offer E2E anymore.

## Do not
- Flip publish/orders gates without Clay signature
- Place supplier Process orders

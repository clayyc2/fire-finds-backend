# Launch readiness report (updated 2026-09-05)

Generated: `2026-09-05`
**Overall:** `NOT_READY_FOR_LIVE` (Sandbox Offer unblocked; live eBay user token not on this runner)

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
| Sandbox web UI sign-in | **BROKEN** | `signin.sandbox.ebay.com` 403/Akamai |
| Randmar OAuth/account read | **PASS** | Dedicated Order Router client; V4 account 200 |
| Randmar cart AddItem | **PASS** | no-purchase probe 200/`true` |
| Randmar shipping quote | **PASS** | 200 + carrier method IDs |
| Randmar `ProcessNew` | **NOT RUN** | hard-gated |
| eBay paid-order ingest | **CODE COMPLETE; LIVE READ PENDING** | `SEEN→MAPPED→ROUTED_OFF` simulated |
| Unit suite on this runner | **181 passed** | pytest after ingest/capacity additions |
| eBay Sandbox user token on this runner | **MISSING** | secret + refresh token not in this environment |

## Clay-only remaining
1. Put Sandbox `EBAY_CLIENT_SECRET` and user refresh token in this runner secret store (mode 600). Do not paste into chat.
2. Run read-only Sandbox GETs: privilege, orders, three policies, locations, payments program.
3. Keep ingest at `ROUTED_OFF` until Clay approves ProcessNew.
4. Sign `docs/CLAY_GO_LIVE_AUTHORIZATION_BRIEF.md` before any production publish or supplier order.

## Do not
- Flip publish/orders gates without Clay signature
- Place supplier Process orders

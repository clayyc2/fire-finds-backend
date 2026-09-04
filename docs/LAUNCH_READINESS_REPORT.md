# Launch readiness report (pointer)

**Latest:** `data/reports/launch_readiness_20260904_2004.md` (+ `.json`)

**Overall:** `BLOCKED_CLAY` · Freeze `20260904_1348` · SAFE **127** · listable **152**

Publish/orders **OFF**. Clay blockers: Sandbox seller registration + 3 Business Policy IDs, then explicit go-live auth.

Generated: `2026-09-04T20:04:43.031851+00:00`
**Overall:** `BLOCKED_CLAY` (fails=1)

**Publish / supplier orders: OFF** — stop before irreversible go-live; Clay signature required.

## Authoritative freeze

| Metric | Value |
|--------|------:|
| Snapshot | `20260904_1348` |
| SAFE_NATIONWIDE | **127** |
| DESTINATION_SENSITIVE | **25** |
| QUARANTINE_UNRESOLVED | **85** |
| Listable / ranked (DB) | **152 / 152** |

## Pass/fail matrix

| Item | Status | Evidence |
|------|:------:|----------|
| Freeze pointer 20260904_1348 | **PASS** | SAFE 127 / DEST 25 / Q 85; DB listable/ranked 152/152 after attrition sync 90d39f1 |
| Production Browse (App/Cert) | **PASS** | client-credentials 200 + Browse CA search 200; portal UI visual check declined |
| Sandbox user OAuth refresh token | **PASS** | secrets/ebay_user_refresh_token.txt mode 600; scopes inventory/account/fulfillment |
| Sandbox Inventory E2E Final 5 | **PASS** | 5/5 createOrReplace; sandbox_inventory_offer_e2e_20260904T195008Z |
| Sandbox Offer E2E Final 5 | **FAIL** | 0/5 — needs real Business Policy IDs (categoryIds fixed to 16204/112529; policies still placeholders). sellerRegistrationCompleted=false |
| Publish hard-refuse | **PASS** | 5/5 refused while EBAY_SANDBOX_PUBLISH_ENABLED=false |
| Final 5 v2.1 in SAFE_NATIONWIDE | **PASS** | all in SAFE=True |
| First-wave 25 dry-runs | **PASS** | 25/25 PASS on 20260904_1311 lock; membership locked |
| First-wave 25 still SAFE on 1348 | **PASS** | 25/25 in SAFE; missing=[] |
| Authorized images Final 5 | **PASS** | launch_prep_creative_1348.json final5_v2_1.all_ok |
| Authorized images first-wave 25 | **PASS** | all_have_randmar_images |
| Band-A keep ORIGINAL/images | **PASS** | HPW2020XC, 194850506413, 6100176 |
| MAP / no_competition gates | **PASS** | no_competition hard-fail; Final5 competitive-at-MAP on 1348 shortlist; Band-B HOLD |
| Listing-limit / kill switches | **PASS** | ops 16 rules; kill switches false; launch_prep_1348_ops_validation 9/9 |
| Ops order/tracking/cancel/return sims | **PASS** | data/ops/launch_prep_1348_ops_validation.md — 9/9 PASS, no Process |
| Pricing/stock sync (Randmar read-only) | **PASS** | last ingest 2026-09-04T07:12:51Z upserted; health ok; hourly routine paused (resource_exhausted) — one-shot scan clean |
| Go-live authorization brief | **PASS** | docs/CLAY_GO_LIVE_AUTHORIZATION_BRIEF.md (PREP ONLY) |
| First live wave prepared (not published) | **PASS** | Final5 / Wave10 / Wave25 locked; shortlist 1348 refreshed |

## Clay-only remaining blockers

- TESTUSER_shopfirefindsnow: complete seller registration (sellerRegistrationCompleted=true) via https://www.sandbox.ebay.com/sl/sell
- Create EBAY_CA payment/return/fulfillment Business Policies; send 3 real policy IDs (never fabricate)
- Explicit irreversible go-live authorization before any publish or supplier orders (sign docs/CLAY_GO_LIVE_AUTHORIZATION_BRIEF.md phases)

## Proposed first live wave (prepared, NOT published)

**Final 5 (Wave 5):**

```
0ZD3500TRC638MEF8GM5
U2FXR9B3X0GWJ4QZHY7K
F5ON8QFP5D4DP8TDEPYZ
Y37ECLH683SESD119MDT
O5GXH5VHEFJZZ71YR7MZ
```

Full Wave 25 lock + go-live phases: `docs/CLAY_GO_LIVE_AUTHORIZATION_BRIEF.md`

## Notes

- CategoryIds for Final 5 already fixed (toners `16204`, headphones `112529`); Offer still needs **real policy IDs**.
- Hourly Randmar refresh routine remains paused (`resource_exhausted`); last successful ingest recorded; one-shot ops scan clean.
- Portal keys-page visual verify was declined; API Production Browse retest stands.

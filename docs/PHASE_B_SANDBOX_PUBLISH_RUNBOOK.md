# Phase B — Sandbox publish runbook (Final 5 only)

**Status:** PREP / RUNBOOK ONLY — does **not** flip gates or publish.  
**Author:** Sandy Cheeks · `2026-09-04T20:14:26.464125+00:00` (UTC) / America/Edmonton  
**Stay dark with Clay** until Mr. Krabs presents go-live brief for signature.  
**Band-B:** **HOLD** · **No production** · **No Process** · **No supplier orders**

**Ties to:** `docs/CLAY_GO_LIVE_AUTHORIZATION_BRIEF.md` Phase **B** · Phase A MET (`docs/LAUNCH_READINESS_REPORT.md` = `READY_FOR_CLAY_AUTH`) · Inventory/Offer E2E `data/reports/sandbox_inventory_offer_e2e_20260904T201135Z.md`

Companion: `data/reports/phase_b_sandbox_publish_runbook.md` (+ `.json`).

---

## 1. Purpose

Execute a **time-boxed sandbox marketplace publish** of the locked Final 5 to prove publish → listing shape → unpublish, then restore all gates **OFF**.

This is **not** Phase C (production live) and **not** Day-1 measure.

---

## 2. Preconditions (must all be true before gate window)

| # | Check | Evidence / rule |
|---|--------|-----------------|
| 1 | Clay **Phase B** signed | `docs/CLAY_GO_LIVE_AUTHORIZATION_BRIEF.md` signature block — phase B + Final 5 SKU list + date + owner |
| 2 | Phase A MET | Inventory **5/5** + Offer **5/5** on Final 5 |
| 3 | `EBAY_ENV=sandbox` | Production Sell not in play |
| 4 | Business policies present | Real sandbox payment/return/fulfillment policy IDs (Account API path OK) |
| 5 | User refresh token usable | Sandbox Sell scopes inventory/account/fulfillment |
| 6 | CategoryIds fixed | Toners `16204`, headphones `112529` |
| 7 | Gates currently OFF | See §3 starting state |
| 8 | Owner online | CTO (or named operator) to flip gates + run Sell publish; Squidward on standby for listing verify |

**Hard excludes:** Wave 10/25, Band-A keeps, Band-B, DEST, quarantine, any SKU not in §4.

---

## 3. Gate matrix

### Starting state (required)

| Gate | Value |
|------|-------|
| `LIVE_LISTINGS_ENABLED` | **false** |
| `EBAY_SANDBOX_PUBLISH_ENABLED` | **false** |
| `EBAY_PRODUCTION_ENABLED` | **false** |
| `SUPPLIER_ORDERS_ENABLED` | **false** |
| `EBAY_ENV` | `sandbox` |

### Window state (Phase B only — after Clay signature)

| Gate | Value | Notes |
|------|-------|-------|
| `EBAY_SANDBOX_PUBLISH_ENABLED` | **true** | **Only** gate that flips for Phase B |
| `LIVE_LISTINGS_ENABLED` | **false** | Never true in Phase B |
| `EBAY_PRODUCTION_ENABLED` | **false** | Never true in Phase B |
| `SUPPLIER_ORDERS_ENABLED` | **false** | Never true in Phase B — **no Process** |
| `EBAY_ENV` | `sandbox` | |

### Ending state (required before operator walks away)

Same as starting state — all four publish/orders gates **false**.

---

## 4. SKU allowlist (LOCKED Final 5)

```
0ZD3500TRC638MEF8GM5
U2FXR9B3X0GWJ4QZHY7K
F5ON8QFP5D4DP8TDEPYZ
Y37ECLH683SESD119MDT
O5GXH5VHEFJZZ71YR7MZ
```

Operator must pass an explicit allowlist / SKU filter. **Refuse** any publish call outside this set.

---

## 5. Ordered procedure

### Step 0 — Briefing (T−5 min)

1. Confirm Clay Phase B signature on file (photo/copy in ops notes).  
2. Confirm allowlist = Final 5 only.  
3. Open evidence folder path: `data/reports/phase_b_sandbox_run_YYYYMMDD_HHMM/` (create at start).  
4. Record gate snapshot (all OFF) to `gates_before.json`.

### Step 1 — Gate window open

1. Set **only** `EBAY_SANDBOX_PUBLISH_ENABLED=true`.  
2. Re-read env/runtime; abort if any of `LIVE_LISTINGS` / `EBAY_PRODUCTION` / `SUPPLIER_ORDERS` is true.  
3. Record `gates_window_open.json`.

### Step 2 — Publish (sandbox)

1. For each Final 5 SKU in order (§4): publish Offer/listing via existing sandbox Sell path (CTO CLI/service — same stack as E2E that previously asserted refuse).  
2. Per SKU: capture API response (listing ID / offer ID / errors) to `publish_<sku>.json`.  
3. **Stop the wave** if any SKU fails hard (auth, policy, unexpected production endpoint). Do not continue to remaining SKUs until root-caused.  
4. Target: **5/5 published** in sandbox (or document partial + kill).

### Step 3 — Verify

1. Fetch each listing/offer; confirm: sandbox marketplace, correct SKU/title/categoryId, policies attached, price ≥ MAP, `ORIGINAL` creative present.  
2. Confirm **not** visible as production EBAY_CA live store inventory.  
3. Write `verify_summary.md` (pass/fail per SKU).  
4. Optional: one sandbox “view item” screenshot per SKU into evidence folder (no Clay ping).

### Step 4 — Unpublish / clean up

1. Unpublish / withdraw / end each sandbox listing for Final 5 (Sell API or equivalent).  
2. Confirm no Final 5 offers remain published in sandbox.  
3. Write `unpublish_<sku>.json` + `unpublish_summary.md`.

### Step 5 — Gate window close (mandatory)

1. Set `EBAY_SANDBOX_PUBLISH_ENABLED=false`.  
2. Confirm all four gates false + `EBAY_ENV=sandbox`.  
3. Record `gates_after.json`.  
4. **Success =** no Final 5 sandbox listings live **and** `EBAY_SANDBOX_PUBLISH_ENABLED=false`.

### Step 6 — Report

1. Write `data/reports/phase_b_sandbox_run_YYYYMMDD.md` (+ json): counts published/verified/unpublished, duration, blockers, gate hashes.  
2. Notify **Mr. Krabs** only (Sandy stays dark with Clay).  
3. Phase C remains **blocked** until separate Clay signature + Day-1 pack (`docs/FINAL5_DAY1_MEASURE_KILL_PACK.md`).

---

## 6. Abort / rollback (any step)

If anything looks production-bound, Process-adjacent, or allowlist-violating:

1. **Stop publishes immediately.**  
2. Unpublish any Final 5 sandbox listings already created.  
3. Force gates to §3 starting state.  
4. Capture `abort_reason.md`.  
5. Escalate to Mr. Krabs — do **not** retry publish without new go-ahead.

**Never:** Cart/Process, `--inject-ship`, flat ship, Band-B requote, Wave10/25 expand, Clay DM from Sandy, Store purchase.

---

## 7. Roles

| Role | Duty |
|------|------|
| **Clay** | Sign Phase B only (via Mr. Krabs presentation) |
| **Mr. Krabs** | Authorize run start after signature; receive report |
| **CTO** | Gate flips, Sell publish/unpublish, evidence capture |
| **Squidward** | Listing shape verify; no Process |
| **Sandy** | This runbook; stay dark; no gate flips |
| **SpongeBob / Plankton** | Not in critical path for Phase B |

---

## 8. Exit criteria (Phase B done)

- [ ] Clay Phase B signature on file  
- [ ] Final 5 sandbox publish attempted with evidence  
- [ ] Verify pass (or documented fails + abort)  
- [ ] All Final 5 unpublished / cleaned  
- [ ] `EBAY_SANDBOX_PUBLISH_ENABLED=false` and other gates still false  
- [ ] Run report filed under `data/reports/phase_b_sandbox_run_*`  
- [ ] Mr. Krabs notified  

Unlock checklist §2 sandbox publish line can then be marked complete by CTO.

---

## 9. Explicit non-goals

- No production publish (Phase C)  
- No `LIVE_LISTINGS_ENABLED`  
- No `SUPPLIER_ORDERS_ENABLED` / Process  
- No Band-B / Wave25 rewrite  
- No Clay ping from Sandy  
- No Store purchase  

---

## 10. Related

- Go-live brief: `docs/CLAY_GO_LIVE_AUTHORIZATION_BRIEF.md`  
- Readiness: `docs/LAUNCH_READINESS_REPORT.md`  
- Offer E2E green: `data/reports/sandbox_inventory_offer_e2e_20260904T201135Z.md`  
- Unlock checklist §2: `docs/EBAY_UNLOCK_CHECKLIST.md`  
- Day-1 (Phase C): `docs/FINAL5_DAY1_MEASURE_KILL_PACK.md`  
- Pack v2.1: `docs/SANDBOX_PILOT_PACK_v2.md`  

# Clay go-live authorization brief (PREP ONLY)

**Author:** Sandy Cheeks (Fire Finds BD)  
**Prepared:** `2026-09-04T20:03:34+00:00 (UTC)` / `2026-09-04 14:03 MT (America/Edmonton)`  
**Status:** **PREP / docs only** — no outreach, no payments, no publish, **no gate flips**.  
**Stay dark with Clay** until this brief is intentionally presented.  
**Live freeze:** `20260904_1348` — SAFE **127** / DEST **25** / QUAR **85** / ranked listable **152**.  
**Band-B:** **HOLD** (no recovery proposed).

**Non-live E2E (2026-09-04):** Inventory Final 5 **5/5 OK**; Offer **0/5** blocked on `Invalid value for categoryId`; publish refused (expected). Phase A precondition = Offer green. See `data/reports/non_live_e2e_status_20260904_1348.md`.

Companion copy: `data/reports/clay_go_live_authorization_brief.md`.

---

## 1. Purpose — what Clay would authorize in writing

This brief is the **authorization packet** Clay would sign before any Sell publish path opens. It separates **sandbox validation** from **production live** so gates can be named, scoped to an exact SKU list, and rolled back.

| Phase | What Clay authorizes | Gate(s) that may flip (only after signature) | Scope |
|-------|----------------------|-----------------------------------------------|-------|
| **A — Sandbox §2 validate** | Inventory/Offer validation for named Final 5 only; publish still refused unless sandbox publish explicitly named | Optional: `EBAY_SANDBOX_PUBLISH_ENABLED=true` **only** for the named sandbox SKU set, then restore **OFF** | Final 5 locked list |
| **B — Sandbox publish (optional)** | Publish Final 5 to **sandbox** marketplace for end-to-end proof | `EBAY_SANDBOX_PUBLISH_ENABLED` for window; `EBAY_PRODUCTION_ENABLED` stays **false**; `LIVE_LISTINGS_ENABLED` stays **false** | Final 5 |
| **C — Production live Wave 5** | First controlled **production** live probe | `LIVE_LISTINGS_ENABLED` (+ `EBAY_PRODUCTION_ENABLED` if required) for Wave 5 window only | Final 5 |
| **D — Wave 10 / Wave 25** | Expansion only after Wave 5 measures clean | Same production gates for the newly named SKU list | Wave 10 then Wave 25 (locked membership) |

**Default until signed:** every publish/orders gate remains **OFF**. This document does **not** flip anything.

---

## 2. Exact gate checklist — currently OFF

Confirm in `.env` / runtime (do not flip here):

| Gate | Required value now | Notes |
|------|--------------------|-------|
| `LIVE_LISTINGS_ENABLED` | **false** | Production live listings |
| `EBAY_SANDBOX_PUBLISH_ENABLED` | **false** | Sandbox Sell publish |
| `EBAY_PRODUCTION_ENABLED` | **false** | Production Sell API |
| `SUPPLIER_ORDERS_ENABLED` | **false** | Supplier Cart/Process — **separate** unlock; out of scope for listing publish |
| `EBAY_ENV` | `sandbox` (until Phase C) | Production only after Phase C authorization |

**What Clay must authorize to proceed past prep:** named phase (A/B/C/D) + exact SKU list + date + owner signature (block below). Sell has been **RuName / OAuth / publish-gated** historically; checklist §1b may show sandbox RuName+token present, but **publish gates stay OFF** until Clay signs.

---

## 3. Proposed SKU lists (locked dry-run ranks)

**Membership lock:** Final 5 / Wave 10 / Wave 25 = dry-run green set on `20260904_1311` (**25/25 PASS**).  
**Live ranking source (does not auto-replace membership):** `data/reports/first_wave_shortlist_prep_20260904_1348.md`.

### Final 5 (Wave 5) — LOCKED

```
0ZD3500TRC638MEF8GM5
U2FXR9B3X0GWJ4QZHY7K
F5ON8QFP5D4DP8TDEPYZ
Y37ECLH683SESD119MDT
O5GXH5VHEFJZZ71YR7MZ
```

### Wave 10 — LOCKED (Final 5 + ranks 6–10)

```
0ZD3500TRC638MEF8GM5, U2FXR9B3X0GWJ4QZHY7K, F5ON8QFP5D4DP8TDEPYZ, Y37ECLH683SESD119MDT, O5GXH5VHEFJZZ71YR7MZ,
6200164, 6200118, 6CV9945ECFPRW98R5RS8, BRHGE2215PK, CWUFB6L5BLBEB9RECU7D
```

### Wave 25 — LOCKED (ranks 1–25)

```
0ZD3500TRC638MEF8GM5, U2FXR9B3X0GWJ4QZHY7K, F5ON8QFP5D4DP8TDEPYZ, Y37ECLH683SESD119MDT, O5GXH5VHEFJZZ71YR7MZ,
6200164, 6200118, 6CV9945ECFPRW98R5RS8, BRHGE2215PK, CWUFB6L5BLBEB9RECU7D,
BRHGES6215PK, 4JJVETGY26K4WD1PU40Y, 2W43JDNLTDQY8TJSKJLO, X5BG2OVHY728RFYNKXGM, BRHGE2315PK,
1Y3O73Y5FTLXYWT9ZGMH, 0WS8W3TN7Y567E23KJQ3, 15JDPWYSL4VD4BW3T0FB, KLPY96RV627XQ02J3PQB, 5DBZT9XU2KQOXS6VTR1X,
UVVJGGWHN91TVNSMCSFR, BRHGES2415PK, 6200189, 0L9MMHWRPFN80HZOW2ET, 1EZB2PPX2JXPR73B8G1J
```

### 1348 shortlist deltas (informational — not membership swaps)

- **Final 5 intact:** all five still SAFE competitive-at-MAP on `20260904_1348`; all sit in top **6** of the live stock-depth shortlist (order shifted; Band-A `HPW2020XC` inserts at live #2).
- **Wave25 not silently replaced:** 6 locked SKUs fall outside new top-25 by stock-depth rank but remain competitive-eligible (`4JJVETGY26K4WD1PU40Y`, `15JDPWYSL4VD4BW3T0FB`, `UVVJGGWHN91TVNSMCSFR`, `6200189`, `0L9MMHWRPFN80HZOW2ET`, `1EZB2PPX2JXPR73B8G1J`).
- **Band-A keeps in book (not auto-wave):** `HPW2020XC`, `194850506413`, `6100176` — require **separate** Clay add if included in any live wave.
- **New vs locked wave25 in live top-25:** Band-A ×3 + `BRHGE2415PK`, `V70FWDC5QHYL4K95WU29`, `YPSJLSFVFN2TLEXK3659`.

---

## 4. Preconditions (must be true before any gate flip)

1. **RuName / Sell user OAuth** — sandbox §1b configured and token usable; re-confirm if stale. Production user OAuth only if Phase C+ requires it.
2. **Business policy IDs** — payment / return / fulfillment policy IDs real and stored securely (**never fabricate**).
3. **Dry-runs PASS** — Final 5 **5/5** and Wave 25 **25/25** on `data/reports/first_wave_25_dry_runs_20260904_1311.md` (gates OFF simulations).
4. **`no_competition` HARD FAIL** — zero official Browse CA comps remain rejected; no soft first-listing (Clay policy 2026-09-04).
5. **MAP policy** — never recommend / authorize selling below MAP; `uncompetitive_at_map` SKUs stay out of primary waves; hold-at-MAP only with explicit warning.
6. **Sandbox §2** — Inventory/Offer validation clean for the named SKU set (categoryId / specifics resolved — see unlock checklist §2 blockers).
7. **Cohort** — SAFE_NATIONWIDE only for these waves; DEST / QUAR excluded; Band-B HOLD.
8. **Fee posture** — NIS for waves 5/10/25; **no Store purchase required** at this scale.

---

## 5. Explicit non-asks (out of scope for this signature)

- **No payment** / no funds movement authorization
- **No eBay Store purchase** yet (NIS headroom sufficient through Wave 25)
- **No supplier outreach** / no Randmar Cart-Process / `SUPPLIER_ORDERS_ENABLED` flip
- **No Band-B recovery** proposal
- **No bulk publish** of full SAFE 127 / ranked 152
- **No silent Final5 / Wave25 SKU swaps** from 1348 shortlist churn

---

## 6. Signature block — blank for Clay

```
CLAY GO-LIVE AUTHORIZATION
==========================
Date (America/Edmonton): ____________________

Phase authorized (circle one):  A sandbox validate  /  B sandbox publish  /  C production Wave 5  /  D Wave 10  /  D Wave 25

SKU list authorized (paste or attach):
____________________________________________________________________
____________________________________________________________________

Gates authorized to flip for this window only (initials):
  [ ] EBAY_SANDBOX_PUBLISH_ENABLED
  [ ] EBAY_PRODUCTION_ENABLED
  [ ] LIVE_LISTINGS_ENABLED
  [ ] SUPPLIER_ORDERS_ENABLED   ← default leave UNCHECKED / OFF

Restore all publish/orders gates OFF after window:  [ ] yes

Owner (Clay C) signature: ____________________
Printed name: ____________________
Witness / BD note (optional): ____________________
```

---

## Related artifacts

- Live shortlist: `data/reports/first_wave_shortlist_prep_20260904_1348.md`
- Wave playbook: `docs/STAGE2_WAVE_SIZING_PLAYBOOK.md`
- Unlock checklist: `docs/EBAY_UNLOCK_CHECKLIST.md`
- Dry-runs: `data/reports/first_wave_25_dry_runs_20260904_1311.md`
- Pack v2.1: `docs/SANDBOX_PILOT_PACK_v2.md`

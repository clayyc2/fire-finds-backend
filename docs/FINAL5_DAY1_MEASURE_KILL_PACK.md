# Final 5 Day-1 measure + kill/rollback pack

**Status:** PREP ONLY — does **not** authorize publish, gate flips, Band-B, or Clay outreach.  
**Author:** Sandy Cheeks · `2026-09-04T20:08:32.510552+00:00` (UTC) / America/Edmonton  
**Freeze context:** `20260904_1348` · SAFE **127** · listable **152** · Band-B **HOLD**  
**Ties to:** `docs/CONVERSION_EXPERIMENT_DESIGN_v1.md` · `docs/CLAY_GO_LIVE_AUTHORIZATION_BRIEF.md` phases **C → D** · `docs/LAUNCH_READINESS_REPORT.md`

Companion: `data/reports/final5_day1_measure_kill_pack.md` (+ `.json`).

---

## 1. Purpose

When Clay authorizes **Phase C** (production live Wave 5), this pack is the **Day-1 operating scorecard**: what to measure, when to kill a SKU or the whole wave, how to roll back gates, and what must be green before **Phase D** (Wave 10 / 25).

**Creative arm Day-1:** `ORIGINAL_SUPPLIER` baseline only (`AI_ENHANCED` deferred per conversion design).

---

## 2. Scope SKUs (LOCKED — Wave 5 / Final 5)

```
0ZD3500TRC638MEF8GM5
U2FXR9B3X0GWJ4QZHY7K
F5ON8QFP5D4DP8TDEPYZ
Y37ECLH683SESD119MDT
O5GXH5VHEFJZZ71YR7MZ
```

| Rule | Value |
|------|-------|
| Cohort | `SAFE_NATIONWIDE` only |
| Creative | `ORIGINAL_SUPPLIER` |
| Fee posture | **NIS** (≤250 GTC; no Store buy) |
| `comparison_cohort_id` | `conv_exp_v1_wave5_YYYYMMDD` (set at first live publish) |
| Exclude | DEST, quarantine, Band-B, Band-A keeps (unless Clay separately adds) |

---

## 3. Phase map (go-live brief)

| Brief phase | This pack | Gates (only after Clay signature) |
|-------------|-----------|-------------------------------------|
| A/B Sandbox | Out of scope here (Offer still `BLOCKED_CLAY` on policies) | Sandbox only |
| **C — Production Wave 5** | **Day-1 measure + kill applies** | `LIVE_LISTINGS_ENABLED` (+ `EBAY_PRODUCTION_ENABLED` if required); `SUPPLIER_ORDERS_ENABLED` stays **false** unless separately authorized |
| **D — Wave 10 / 25** | Only after **expand gate** below is green | Same production gates for newly named locked SKU list |

---

## 4. Day-1 scorecard (per SKU)

Pull / export learning fields (CTO: `sku-record export-learning` filtered by `comparison_cohort_id`). Currency **CAD**.

| Metric | Field | Day-1 watch |
|--------|-------|-------------|
| Impressions | `impressions` | Zero after 24h live → investigate visibility / category |
| CTR | `ctr` | Near-zero with impressions → title/thumb issue (SpongeBob later) |
| CVR | `conversion_rate` | orders/clicks (keep definition constant) |
| Time to first sale | `time_to_first_sale` | Hours publish → first paid order (nullable) |
| Realized profit | `contribution_profit_realized` | After fees + resolved ship + COGS |
| Units | `sales_units` | Paid units |
| Cancels / returns | `cancellations`, `returns` | Guardrail |
| Creative keys | `creative_variant=ORIGINAL_SUPPLIER`, `ab_assignment`, `comparison_cohort_id` | Must be stamped |

### Cadence

| Window | Who | Action |
|--------|-----|--------|
| T+2h | Squidward / CTO | Listing live? gate still scoped to Final 5? no Process |
| T+24h | Sandy → Mr. Krabs | First scorecard snapshot (impressions/CTR/errors) |
| T+72h | Sandy → Mr. Krabs | Full Day-1 pack review vs kill criteria |
| T+7d | Mr. Krabs | Expand-gate decision for Phase D (or hold) |

---

## 5. Kill criteria (hard)

**SKU-level kill** (end that listing / pause SKU; keep other Final 5 up unless wave kill):

1. **MAP / policy incident** — any below-MAP sell, channel-auth flag, or policy strike
2. **Cancel/return spike** — ≥2 cancels **or** ≥2 returns on the SKU within 7d, or cancel+return rate ≥50% of orders when orders ≥2
3. **Ops exception class** — any `SHIPPING_UNRESOLVED` / fulfillment failure that cannot clear without Process invent / flat inject
4. **Negative realized contribution** after ≥1 sale once fees+ship applied (not just provisional)
5. **Gate drift** — SKU published outside authorized list or `SUPPLIER_ORDERS` flipped without Clay auth

**Wave-level kill** (disable live wave immediately):

1. Any **account-level** eBay policy / selling-limit lock / payment hold
2. **≥3 of 5** Final 5 SKUs hit SKU-level kill
3. Unauthorized gate flip (`LIVE_LISTINGS` / production / sandbox publish / supplier orders) detected outside Clay-signed window
4. Data integrity: learning export missing `comparison_cohort_id` for live SKUs after T+24h with no CTO fix in flight

**Band-B:** remains **HOLD** — kill pack does **not** authorize quarantine recovery chase during Day-1.

---

## 6. Rollback procedure (ordered)

Execute top-down; stop when wave is inert. **No Process. No Clay ping from Sandy.**

1. **End / unpublish** live Final 5 listings (Squidward/CTO Sell path)
2. Set `LIVE_LISTINGS_ENABLED=false`
3. Set `EBAY_PRODUCTION_ENABLED=false` (if it was true)
4. Confirm `EBAY_SANDBOX_PUBLISH_ENABLED=false`, `SUPPLIER_ORDERS_ENABLED=false`
5. Snapshot evidence under `data/reports/final5_day1_rollback_YYYYMMDD.*` (SKU states, gate values, reason codes)
6. Mr. Krabs decides: hold / fix / re-authorize with new Clay signature

Rollback is **success** when: no Final 5 listings remain live **and** all four publish/orders gates read **false**.

---

## 7. Phase D expand gate (Wave 5 → Wave 10)

All must be true before presenting Phase D for Clay signature:

| # | Gate | Pass rule |
|---|------|-----------|
| 1 | Wave kill not fired | No wave-level kill in window |
| 2 | SKU kills | ≤1 SKU killed **or** killed SKUs replaced only via new Clay-signed list (no silent swap) |
| 3 | Measure window | ≥**72h** live on ORIGINAL baseline with learning rows for all still-live Final 5 |
| 4 | Economics | Aggregate `contribution_profit_realized` ≥ 0 across Final 5 with ≥1 sale **or** clear "no sales yet but healthy impressions/CTR" note with Mr. Krabs OK to expand for learning |
| 5 | Ops | No open P0 ops exceptions on Final 5; supplier orders still OFF unless separately authorized |
| 6 | Membership | Next list = **locked Wave 10** only (Final 5 + `6200164, 6200118, 6CV9945ECFPRW98R5RS8, BRHGE2215PK, CWUFB6L5BLBEB9RECU7D`); no Band-A auto-add |

Wave 25 expand: same table after Wave 10 measures clean ≥72h (or Clay-defined window).

---

## 8. Roles

| Role | Day-1 duty |
|------|------------|
| **Sandy** | Scorecard draft, kill/expand recommendation to Mr. Krabs; stay dark with Clay |
| **Mr. Krabs** | Prioritize kill/expand; only path to Clay for auth |
| **CTO** | Gates, learning export schema, listing end/rollback mechanics |
| **Squidward** | Ops exceptions, stock/price sync watch (no Process) |
| **SpongeBob** | Creative only if ORIGINAL gap; AI_ENHANCED still deferred |
| **Plankton** | No Day-1 research thrash; MAP/compete hygiene only if kill reason is competition |

---

## 9. Explicit non-goals

- No publish from this document
- No Clay outreach / policy-ID collection by Sandy
- No Band-B / quarantine Estimate chase
- No AI_ENHANCED A/B until assets + Clay approve (conversion design phase 4)
- No Store purchase (NIS for Wave 5–25)
- No `SUPPLIER_ORDERS_ENABLED` flip inside this pack

---

## 10. Related

- Conversion design: `docs/CONVERSION_EXPERIMENT_DESIGN_v1.md`
- Go-live brief phases C→D: `docs/CLAY_GO_LIVE_AUTHORIZATION_BRIEF.md`
- Readiness: `docs/LAUNCH_READINESS_REPORT.md` (`BLOCKED_CLAY` until policies)
- Wave lock: `docs/STAGE2_WAVE_SIZING_PLAYBOOK.md`
- Ops exceptions: `docs/OPS_EXCEPTIONS.md`

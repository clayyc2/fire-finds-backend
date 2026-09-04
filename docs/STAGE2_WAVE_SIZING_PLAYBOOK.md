# Stage-2 wave sizing playbook (Final 5 → 10 → 25)

**Status:** PREP ONLY — **blocked** until RuName → sandbox §2 → Clay live approval. **No publish.**  
**Author:** Sandy Cheeks · `2026-09-04T19:19:16+00:00 (UTC) / 2026-09-04 13:19 MDT (America/Edmonton)`  
**Stay dark with Clay** — no payments, outreach, gate flips, or `LIVE_LISTINGS` / `SUPPLIER_ORDERS` / `EBAY_*` flips.  
**Live freeze:** `20260904_1348` — SAFE **127** / DEST **25** / QUAR **85** / ranked **152**.  
**Dry-runs:** **25/25 PASS** — `data/reports/first_wave_25_dry_runs_20260904_1311.md` (+ `.json`). Final 5 also on pack v2.1 `data/reports/sandbox_pack_v2_dry_runs.md` (5/5 PASS).

Companion copy: `data/reports/stage2_wave_sizing_playbook.md`.

## Hard gate (explicit)

```
RuName configured
  → sandbox §2 (inventory/offer validation; publish gate still OFF until named)
    → Clay written live approval (SKU list + date + owner)
      → only then consider Stage-3 small controlled live wave
```

Until that chain completes: **no publish**, gates stay OFF (`LIVE_LISTINGS_ENABLED`, `EBAY_SANDBOX_PUBLISH_ENABLED`, `EBAY_PRODUCTION_ENABLED`, `SUPPLIER_ORDERS_ENABLED` = false).

## Wave sizes

| Wave | Size | Role | Fee posture | Selling-limit / insertion note |
|------|-----:|------|-------------|-------------------------------|
| **Final 5 / Wave 5** | 5 | Sandbox + first live probe | **NIS** | ≪ account selling limits; ≪ 250 NIS free GTC insertions |
| **Wave 10** | 10 | First expansion after Final 5 measures clean | NIS | Still under NIS 250; soft-respect `EBAY_SELLING_LIMIT` |
| **Wave 25** | 25 | Second expansion | NIS | Still under NIS 250; Store **not** required until GTC live ≫250 |

**Wave membership (locked to dry-run ranks):** Wave 5 = ranks **1–5**, Wave 10 = ranks **1–10**, Wave 25 = ranks **1–25** from `first_wave_25_dry_runs_20260904_1311` — **all green (25/25 PASS)**.

All three waves fit under NIS free insertion allotment. Store trigger is catalog-scale (≫250 GTC), not wave-25 — see `data/reports/stage2_store_trigger_memo.md`.

## Selection policy

From competitive-at-MAP shortlist / first-wave prep (`first_wave_shortlist_prep_20260904_1224` + deep prep `first_wave_25_prep_deep_20260904_1311`):

1. **`uncompetitive_at_map = False`** only (prefer competitive-at-MAP; never recommend below MAP)
2. **SAFE_NATIONWIDE only** — exclude DESTINATION_SENSITIVE and QUARANTINE_UNRESOLVED
3. **Stock ≥ 5**
4. **`no_competition` = HARD FAIL** — zero official Browse CA comps stay rejected; no soft first-listing (Clay policy 2026-09-04)
5. Prefer shortlist / queue order already used for Final 5 v2.1 (not high-profit contract toner that is uncompetitive-at-MAP)
6. Original creative draft present (all 25 prep-ready on 1311)
7. Dry-run E2E **PASS** (listing+order simulated; gates OFF) — satisfied for all 25


## Wave 5 = Final 5 v2.1 (ranks 1–5 — all dry-run PASS)

| SKU | Stock | MAP | Browse med | Profit | Cohort | Uncomp@MAP |
|-----|------:|----:|-----------:|-------:|--------|:----------:|
| `0ZD3500TRC638MEF8GM5` | 74 | 152.99 | 179.42 | 82.35 | SAFE_NATIONWIDE | False |
| `U2FXR9B3X0GWJ4QZHY7K` | 66 | 128.99 | 152.73 | 66.33 | SAFE_NATIONWIDE | False |
| `F5ON8QFP5D4DP8TDEPYZ` | 79 | 128.99 | 139.055 | 66.33 | SAFE_NATIONWIDE | False |
| `Y37ECLH683SESD119MDT` | 69 | 414.02 | 417.55 | 67.48 | SAFE_NATIONWIDE | False |
| `O5GXH5VHEFJZZ71YR7MZ` | 154 | 177.95 | 155.72 | 31.82 | SAFE_NATIONWIDE | False |

Dry-runs: **5/5 PASS** within the first-wave **25/25** report — `data/reports/first_wave_25_dry_runs_20260904_1311.md`. Prior pack pointer: `data/reports/sandbox_pack_v2_dry_runs.md` (5/5 PASS).

Optional alt only (not primary): `5SU7SO72ZJJZXN39BV1O` (`uncompetitive_at_map`).

## Wave 10 = ranks 1–10 (all dry-run PASS)

Ranks 6–10 (add to Final 5 → total 10):

| SKU | Stock | MAP | Browse med | Profit | Cohort | Uncomp@MAP |
|-----|------:|----:|-----------:|-------:|--------|:----------:|
| `6200164` | 29 | 207.99 | 258.39 | 33.55 | SAFE_NATIONWIDE | False |
| `6200118` | 25 | 356.99 | 392.58 | 70.47 | SAFE_NATIONWIDE | False |
| `6CV9945ECFPRW98R5RS8` | 32 | 135.0 | 137.87 | 23.79 | SAFE_NATIONWIDE | False |
| `BRHGE2215PK` | 33 | 99.99 | 97.67 | 22.49 | SAFE_NATIONWIDE | False |
| `CWUFB6L5BLBEB9RECU7D` | 30 | 125.0 | 125.0 | 18.97 | SAFE_NATIONWIDE | False |

SKU list (ranks 6–10): `6200164, 6200118, 6CV9945ECFPRW98R5RS8, BRHGE2215PK, CWUFB6L5BLBEB9RECU7D`

Notes: ORIGINAL drafts present; **dry-run PASS** for all five (part of 25/25 green on `20260904_1311`).

## Wave 25 = ranks 1–25 (all dry-run PASS)

Ranks 6–25 (add to Final 5 → total 25):

| SKU | Stock | MAP | Browse med | Profit | Cohort | Uncomp@MAP |
|-----|------:|----:|-----------:|-------:|--------|:----------:|
| `6200164` | 29 | 207.99 | 258.39 | 33.55 | SAFE_NATIONWIDE | False |
| `6200118` | 25 | 356.99 | 392.58 | 70.47 | SAFE_NATIONWIDE | False |
| `6CV9945ECFPRW98R5RS8` | 32 | 135.0 | 137.87 | 23.79 | SAFE_NATIONWIDE | False |
| `BRHGE2215PK` | 33 | 99.99 | 97.67 | 22.49 | SAFE_NATIONWIDE | False |
| `CWUFB6L5BLBEB9RECU7D` | 30 | 125.0 | 125.0 | 18.97 | SAFE_NATIONWIDE | False |
| `BRHGES6215PK` | 17 | 107.99 | 134.28 | 22.63 | SAFE_NATIONWIDE | False |
| `4JJVETGY26K4WD1PU40Y` | 5 | 65.0 | 114.96 | 14.83 | SAFE_NATIONWIDE | False |
| `2W43JDNLTDQY8TJSKJLO` | 13 | 260.0 | 330.365 | 44.17 | SAFE_NATIONWIDE | False |
| `X5BG2OVHY728RFYNKXGM` | 15 | 150.0 | 179.0 | 26.21 | SAFE_NATIONWIDE | False |
| `BRHGE2315PK` | 23 | 107.49 | 106.13 | 24.11 | SAFE_NATIONWIDE | False |
| `1Y3O73Y5FTLXYWT9ZGMH` | 14 | 210.0 | 235.0 | 52.58 | SAFE_NATIONWIDE | False |
| `0WS8W3TN7Y567E23KJQ3` | 15 | 78.0 | 91.715 | 19.6 | SAFE_NATIONWIDE | False |
| `15JDPWYSL4VD4BW3T0FB` | 7 | 434.99 | 433.82 | 171.36 | SAFE_NATIONWIDE | False |
| `KLPY96RV627XQ02J3PQB` | 10 | 594.03 | 621.11 | 102.18 | SAFE_NATIONWIDE | False |
| `5DBZT9XU2KQOXS6VTR1X` | 12 | 210.0 | 235.0 | 50.19 | SAFE_NATIONWIDE | False |
| `UVVJGGWHN91TVNSMCSFR` | 7 | 120.0 | 155.65 | 33.65 | SAFE_NATIONWIDE | False |
| `BRHGES2415PK` | 17 | 131.99 | 131.51 | 28.43 | SAFE_NATIONWIDE | False |
| `6200189` | 8 | 204.49 | 245.3 | 33.06 | SAFE_NATIONWIDE | False |
| `0L9MMHWRPFN80HZOW2ET` | 9 | 160.0 | 186.22 | 27.83 | SAFE_NATIONWIDE | False |
| `1EZB2PPX2JXPR73B8G1J` | 7 | 183.99 | 221.54 | 30.86 | SAFE_NATIONWIDE | False |

SKU list (ranks 6–25): `6200164, 6200118, 6CV9945ECFPRW98R5RS8, BRHGE2215PK, CWUFB6L5BLBEB9RECU7D, BRHGES6215PK, 4JJVETGY26K4WD1PU40Y, 2W43JDNLTDQY8TJSKJLO, X5BG2OVHY728RFYNKXGM, BRHGE2315PK, 1Y3O73Y5FTLXYWT9ZGMH, 0WS8W3TN7Y567E23KJQ3, 15JDPWYSL4VD4BW3T0FB, KLPY96RV627XQ02J3PQB, 5DBZT9XU2KQOXS6VTR1X, UVVJGGWHN91TVNSMCSFR, BRHGES2415PK, 6200189, 0L9MMHWRPFN80HZOW2ET, 1EZB2PPX2JXPR73B8G1J`

Wave-25 deep prep: `data/reports/first_wave_25_prep_deep_20260904_1311.md` — **25/25 prep_ready**, 0 uncompetitive.  
Wave-25 dry-runs: `data/reports/first_wave_25_dry_runs_20260904_1311.md` — **25/25 PASS** (Final 5 prior 5/5 + new 20/20).

## Mapping to selling limits / Store insertion (conceptual)

| Live GTC count | NIS free insertions (250) | Store Basic free (1,000) | Recommendation |
|---------------:|--------------------------:|-------------------------:|----------------|
| 5 / 10 / 25 | unused headroom | n/a | Stay NIS |
| ~124–149 (full current book) | still ≤250 | n/a | Stay NIS unless sell-through argues FVF |
| **≫250** | overage $0.30/GTC | fits easily | **Buy Basic Store** before that wave |

Account selling limits (`EBAY_SELLING_LIMIT` / eBay seller limits): soft-respect on every wave; raise limits with eBay before expanding past approved N.

## Sequence (ops)

1. Complete §1b RuName + user OAuth (checklist).
2. Sandbox §2 for Final 5 / Wave 5 only; restore publish gate OFF.
3. Clay live approval for Final 5 → measure (§4).
4. If clean: approve Wave 10 (ranks 1–10), then Wave 25 (ranks 1–25) — each with written SKU list from the dry-run report.
5. Never bulk-publish entire SAFE 124 / ranked 149 without Stage-5 scale approval.

## Related artifacts

- First-wave dry-runs (**25/25 PASS**): `data/reports/first_wave_25_dry_runs_20260904_1311.md`
- Shortlist: `data/reports/first_wave_shortlist_prep_20260904_1224.md`
- Wave-25 deep: `data/reports/first_wave_25_prep_deep_20260904_1311.md`
- Pack v2.1: `docs/SANDBOX_PILOT_PACK_v2.md`
- Unlock checklist: `docs/EBAY_UNLOCK_CHECKLIST.md`
- Fee book: `data/reports/ebay_ca_fee_model_149_book.md`
- Cohort pointer: `data/reports/cohort_refresh_latest.md`

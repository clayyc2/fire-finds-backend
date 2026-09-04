# SAFE_NATIONWIDE sandbox pilot pack (pointer)

**Status:** `PREP_ONLY` — gates still **OFF**. Prep-only documentation; no publish / no orders.

**Do not publish until Clay authorizes sandbox.**

Full draft (gitignored under `data/`):

- `data/reports/sandbox_pilot_pack_draft.md`
- `data/reports/sandbox_pilot_pack_draft.json`
- Dry-run summary (2026-09-04): `data/reports/sandbox_pack_dry_runs_20260904.md` + `.json`

## Cohort snapshot migration

- **Live / current freeze:** `20260904_1224` — SAFE **289** / DEST **46** / QUARANTINE **101** (ranked finally-profitable **335**).
- **Prior freeze (superseded for live ops):** `20260904_0140` — SAFE 275 / DEST 46 / QUARANTINE 113 (stale after wave-2 requote + validate).
- Earlier: `20260903_1744` — SAFE 254 / DEST 42 / QUARANTINE 140.
- Refresh evidence: `data/reports/cohort_refresh_latest.md`.
- Final 5 pilot SKUs below remain in SAFE on `20260904_1224`; Stage 0 dry-run pack **5/5 PASS**; **OAuth still blocked**.
- Dry-run artifacts were produced under earlier snapshot ids (`20260903_1744` / `20260904_0140`).

## Final 5 SKUs (`SAFE_NATIONWIDE` / originally `20260903_1744`; still SAFE on `20260904_1224`)

| # | SKU | Dry-run | Artifact |
|--:|-----|:-------:|----------|
| 1 | `5SU7SO72ZJJZXN39BV1O` (primary) | **PASS** (prior) | `data/dry_runs/5SU7SO72ZJJZXN39BV1O_latest.json` |
| 2 | `JNT6MB6NZM7613W9V3TS` (primary) | **PASS** | `data/dry_runs/JNT6MB6NZM7613W9V3TS_latest.json` |
| 3 | `12TR81JCCQZ3FLFYXF5D` (primary) | **PASS** | `data/dry_runs/12TR81JCCQZ3FLFYXF5D_latest.json` |
| 4 | `KTO9Q03JXGUJ91YXDVUK` (added) | **PASS** | `data/dry_runs/KTO9Q03JXGUJ91YXDVUK_latest.json` |
| 5 | `YCCY3042XFJDNCRSFT6S` (added) | **PASS** | `data/dry_runs/YCCY3042XFJDNCRSFT6S_latest.json` |

All five: `SIMULATED_LISTED` + `SIMULATED_ORDER`; `live_publish=false`; `supplier_order_api_called=false`; feature gates OFF (`LIVE_LISTINGS` / `SUPPLIER_ORDERS` / `EBAY_SANDBOX_PUBLISH`).

Avoided `DESTINATION_SENSITIVE`. Skipped thin-headroom rank-4 `XY45K3YZCNUFODY9HCF5` (stock=3).
Ops re-scan may later pause **stock≤2 only** (stock=3 OK).

Image URLs ready for all five. Creative status: **ORIGINAL_SUPPLIER ready (PREP_ONLY)** — see `data/drafts/randmar_first/safe_nationwide/sandbox_pilot_5_original/` and `data/reports/sandbox_pilot_5_original_creative.json`. AI_ENHANCED deferred.  
Depends on Canada Randmar OAuth + eBay CA sandbox OAuth before any sandbox publish.

See also: `docs/EBAY_UNLOCK_CHECKLIST.md`, `docs/CREATIVE_IMAGERY_STATUS.md`, `docs/SHIPPING_QUOTE_FALLBACK.md`.

Generated: `2026-09-04T01:32:27Z` (UTC). Dry-run status updated: `2026-09-04T06:13:09Z` (UTC) / ~00:13 MDT.

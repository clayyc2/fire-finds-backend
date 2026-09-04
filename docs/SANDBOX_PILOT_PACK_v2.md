# SAFE sandbox pilot pack v2 (competitive-at-MAP / post Browse CA compete)

**Status:** `PREP_ONLY` — gates still **OFF**. Prep-only documentation; no publish / no orders.

**Do not publish until Clay authorizes sandbox** (after Sell user OAuth / RuName).

Replaces Final 5 targeting in `docs/SANDBOX_PILOT_PACK.md` for Stage 2. v1 pack retained as historical.

## Why v2

Official Production Browse competition on snapshot lineage `20260904_1224` cut listable **335 → 149** (`data/reports/ebay_browse_compete_20260904_1224.md`).  
Primary cut: **`no_competition` (233)**.

| v1 SKU | Post-compete |
|--------|----------------|
| `5SU7SO72ZJJZXN39BV1O` | Browse **PASS** but **`uncompetitive_at_map`** (MAP 834 vs median 496.58) — optional alt only |
| `JNT6MB6NZM7613W9V3TS` | FAIL `no_competition` |
| `12TR81JCCQZ3FLFYXF5D` | FAIL `no_competition` |
| `KTO9Q03JXGUJ91YXDVUK` | FAIL `no_competition` |
| `YCCY3042XFJDNCRSFT6S` | FAIL `no_competition` |

**`no_competition` policy (Clay 2026-09-04):** keep **hard-fail** (current). No soft first-listing for zero Browse comps. Final 5 stays competitive-at-MAP v2.1 only.

**Selection policy:** prefer **competitive-at-MAP** rows from `first_wave_shortlist_prep` top of queue — **not** high-profit contract toner that is `uncompetitive_at_map`. Never recommend selling below MAP.

A prior Sandy draft that listed `5SU7…` + `6300439` / `6300441` / `6300550` / `ZP3MJKDHFU7SB8QEZ695` is **superseded** (those are mostly uncompetitive-at-MAP).

## Final 5 v2 (competitive-at-MAP)

Live cohort freeze: **`20260904_1348`** — SAFE **127** / DEST **25** / QUARANTINE **85** (ranked listable **152**).

| # | SKU | MAP | Browse med | Uncomp@MAP | Stock | Dry-run |
|--:|-----|----:|-----------:|:----------:|------:|:-------:|
| 1 | `0ZD3500TRC638MEF8GM5` | 152.99 | 179.42 | False | 74 | **PASS** |
| 2 | `U2FXR9B3X0GWJ4QZHY7K` | 128.99 | 152.73 | False | 66 | **PASS** |
| 3 | `F5ON8QFP5D4DP8TDEPYZ` | 128.99 | 139.055 | False | 79 | **PASS** |
| 4 | `Y37ECLH683SESD119MDT` | 414.02 | 417.55 | False | 69 | **PASS** |
| 5 | `O5GXH5VHEFJZZ71YR7MZ` | 177.95 | 155.72 | False | 154 | **PASS** |

All five: `SIMULATED_LISTED` + `SIMULATED_ORDER`; `live_publish=false`; `supplier_order_api_called=false`; feature gates OFF.

**Optional alt (not primary):** `5SU7SO72ZJJZXN39BV1O` — flagged `uncompetitive_at_map` (`map_68%_above_browse_median`). Hold at MAP; do not undercut.

## Artifacts

- Companion JSON: `data/reports/sandbox_pilot_pack_v2.json`
- Companion MD (data): `data/reports/sandbox_pilot_pack_v2.md`
- Dry-runs: `data/reports/sandbox_pack_v2_dry_runs.md`
- Browse compete: `data/reports/ebay_browse_compete_20260904_1224.md`
- First-wave shortlist: `data/reports/first_wave_shortlist_prep_20260904_1224.md`
- MAP gaps: `data/reports/map_vs_browse_gaps_20260904_1224.md`
- Cohort refresh: `data/reports/cohort_refresh_latest.md`
- Snapshot: `data/snapshots/20260904_1348_shipping_complete/`
- Cohorts: `data/cohorts/20260904_1348/randmar_first/`

## Safety

- `LIVE_LISTINGS_ENABLED=false`
- `EBAY_SANDBOX_PUBLISH_ENABLED=false`
- `EBAY_PRODUCTION_ENABLED=false`
- `SUPPLIER_ORDERS_ENABLED=false`
- No Process / no publish / no `--inject-ship`

Generated: `2026-09-04T19:12:34.419188+00:00` (UTC) / 2026-09-04 13:12 MDT (America/Edmonton).

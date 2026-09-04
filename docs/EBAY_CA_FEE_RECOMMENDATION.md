# eBay CA fee recommendation (research / prep only)

**Status:** recommendation only — gates **OFF**; no Store purchase required by config; no live P&L flip.  
**Live freeze:** snapshot **`20260904_1348`** — SAFE **127** / DEST **25** / QUAR **85** / ranked listable **152**.  
**Canonical fee book:** `data/reports/ebay_ca_fee_model_149_book.md` + `.json` (supersedes historical `ebay_ca_fee_model_321_book.md` for live ops).  
**Store trigger:** `data/reports/stage2_store_trigger_memo.md` · Wave playbook: `docs/STAGE2_WAVE_SIZING_PLAYBOOK.md`.  
**Updated:** `2026-09-04T19:18:55+00:00 (UTC) / 2026-09-04 13:18 MDT (America/Edmonton)`

## Current backend defaults

- `EBAY_FEE_RATE=0.1325` (13.25%)
- `EBAY_FEE_FIXED=0.30`

These sit between typical NIS and Store Basic rates and are fine for **ranking / listable screening**. They do **not** imply a Store subscription.

## Key book numbers (`20260904_1348` ranked 152; prior book on 1311/149)

| Item | CAD |
|------|----:|
| Ranked GMV (1× sell each) | ~55,931 |
| NIS one-shot total fees | ~7,666 |
| Store Basic one-shot total (incl. $19.95) | ~7,183 |
| Store vs NIS (one-shot) | ≈ **−$483** |
| NIS insertion overage at 149 GTC | **$0** (≤250 free) |
| Steady-state Store save @ 20 units/mo | ~$48 |
| Steady-state Store save @ 50 units/mo | ~$149 |
| FVF break-even (approx) | ~6 units/mo |

## When Basic Store is later chosen

If / when the selling account moves to **eBay CA Basic Store** (yearly), update scoring for live P&L modeling to:

| Setting | Recommended | Notes |
|---------|-------------|--------|
| `EBAY_FEE_RATE` | **0.127** (12.7%) | Typical most-category Store Basic FVF (CA) |
| Per-order fee | **$0.40** | Orders > ~$10; prefer modeling as order fee (today’s `EBAY_FEE_FIXED` is a rough proxy — confirm field semantics before live) |

**Buy Store when planned GTC live ≫ 250** (NIS free insertion allotment exhausted). Final 5 / Wave 25 stay **NIS**. Do **not** change live `.env` solely to force a Store buy.

See also: `data/reports/ebay_ca_fee_model_149_book.md`, `data/reports/stage2_store_trigger_memo.md`, `data/reports/bd_scorecards_fee_model_summary_20260904.md` (historical: `ebay_ca_fee_model_321_book.md`).

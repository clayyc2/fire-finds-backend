# eBay CA fee recommendation (research / prep only)

**Status:** recommendation only — gates **OFF**; no Store purchase required by config; no live P&L flip.

## Current backend defaults

- `EBAY_FEE_RATE=0.1325` (13.25%)
- `EBAY_FEE_FIXED=0.30`

These sit between typical NIS and Store Basic rates and are fine for **ranking / listable screening**. They do **not** imply a Store subscription.

## When Basic Store is later chosen

If / when the selling account moves to **eBay CA Basic Store** (yearly), update scoring for live P&L modeling to:

| Setting | Recommended | Notes |
|---------|-------------|--------|
| `EBAY_FEE_RATE` | **0.127** (12.7%) | Typical most-category Store Basic FVF (CA) |
| Per-order fee | **$0.40** | Orders > ~$10; prefer modeling as order fee (today’s `EBAY_FEE_FIXED` is a rough proxy — confirm field semantics before live) |

Do **not** change live `.env` solely to force a Store buy. Comment / `.env.example` guidance is enough until Clay authorizes Store + fee cutover.

See also: `data/reports/ebay_ca_fee_model_321_book.md`, `data/reports/bd_scorecards_fee_model_summary_20260904.md`.

# Shipping quote fallback: Cart/AddItem → ShippingLabel/Estimate

**Status:** operational note (read-only quoting). Gates stay **OFF** — never Process, never invent a flat $10 inject.

## Prefer order

`RandmarQuoteProvider` (`backend/firefinds/scoring/shipping.py`) tries quote sources in order:

1. **`cart_shipping_methods`** — ephemeral cart: `Cart/AddItem/.../DefaultOpportunity` → `Cart/ShippingMethods/{cart}` per destination → `Cart/DELETE`. Never `Cart/Process*`.
2. **`shipping_label_estimate`** — fallback: `POST ShippingLabel/Estimate` with warehouse origin + product `UnitWeight` / `TotalWeight`. Never `ShippingLabel/Generate`.

Multi-dest path (`quote_destinations`): AddItem once, ShippingMethods per dest; **any unresolved / failed cart quote per dest falls back to ShippingLabel/Estimate** for that dest.

Profitability shipping cost = **p75** of resolved representative destinations (Calgary, Vancouver, Toronto, Montreal, Halifax), not a single-city cherry-pick.

## When Cart/AddItem fails

Observed on retail OEM HP toner requotes (`data/ebay_demand_pilot/toner_requote_results.md`):

- **Blocker (non-auth):** `Cart/AddItem HTTP 400 Result is false`
- Cart path cannot build ShippingMethods quotes for those SKUs
- **Fallback OK:** ShippingLabel/Estimate resolved all 7 SKUs (`source=shipping_label_estimate`)
- Enrichment sometimes required: catalog `UnitWeight` + warehouse qtys (DB null/zero columns) before Estimate can succeed (`missing_unit_weight_for_label_estimate` otherwise)

## Ops implications (toner economics)

Shipping **RESOLVED** ≠ **finally listable**.

The 7 OEM toners below got real p75 CAD via Estimate fallback but still fail `$8` profit / `12%` margin at MAP. Tag as **economics-closed** so ops does not thrash requotes:

| SKU | MPN | p75 CAD (approx) |
|-----|-----|------------------|
| 6090488 | CF226A | 18.83 |
| 6090342 | CE285A | 19.20 |
| 6090496 | CF248A | 17.47 |
| 6090084 | Q2612A | 17.68 |
| 6090551 | CF500A | 19.46 |
| 6090287 | CB435A | 17.68 |
| 6090391 | CF280X | 19.46 |

Machine tag: `data/ops/toner_economics_closed.json`  
Evidence: `data/ebay_demand_pilot/toner_requote_results.md` / `.json`

## Hard rules

- Stay dark: `LIVE_LISTINGS_ENABLED`, `SUPPLIER_ORDERS_ENABLED`, eBay publish flags **false**
- Never Process carts; never Generate labels as part of quoting
- Never invent flat inject shipping to force RESOLVED
- Quarantine recovery shortlists must **exclude** this economics-closed toner set

## Code pointers

- Client: `backend/firefinds/clients/randmar.py` — `cart_add_item_default`, `estimate_cart_shipping*`, `estimate_shipping_label` / `shipping_label_estimate`
- Provider: `backend/firefinds/scoring/shipping.py` — `RandmarQuoteProvider.prefer`, `quote_destinations` fallback
- Batch quotes: `backend/firefinds/services_quote.py`

Generated: 2026-09-04 (UTC) from toner requote findings.

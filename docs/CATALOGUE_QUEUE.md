# Offline catalogue queue

No network or AI is used by this queue builder. It evaluates every supplied
catalogue row; it does not truncate to a supplier-generated shortlist.

```sh
python3 scripts/prepare_catalogue_queue.py \
  --catalogue data/fulfillment-readiness/randmar-catalog.json \
  --existing-mapping data/fulfillment-readiness/verified_sku_mapping.json \
  --purchase-audit data/supplier-readiness/listed-buyability.json \
  --out data/listing-preflight/opinion-catalogue-queue.json
```

Inputs and output are private operational data, excluded from Git. The original
catalogue observation time is retained; offline processing does not refresh
supplier facts. Duplicate or missing SKUs fail the run instead of silently
replacing records. Existing live mappings are excluded from new listings.

## Initial opinion

Prioritize replacement ink/toner, then other recurring office consumables,
then small accessories. Lower dealer cost, lighter weight and buffered stock
increase the opinion score. Supplier demand percentiles, outside sales and
competitor prices have no effect. This score is not a sales-probability claim.

Inactive, opportunity-only/unknown, known purchase-denied, insufficient-stock,
missing-cost/MAP/title, heavy and special-program/risk candidates are held.
These screening filters do NOT certify channel permission or fulfillment.
Every remaining candidate still has `publish_ready=false`, a null final price
and an explicit list of outstanding readiness requirements.

## Learning only from Fire Finds

Optional `--own-results` accepts a SKU-keyed JSON object. Each record requires
`source=fire_finds_own_results`, positive `exposure_days`, whole nonnegative
`fulfilled_units`, `returned_units` no greater than fulfilled units, and finite
`net_profit_cad`. Less than seven days retains cold-start opinion ordering.
After seven days, retained units with positive profit rank above untested
products, ordered by retained units/day then profit/day. Weak observed results
rank below untested products. Attribution must be supplied by a trusted
first-party collector; the string label alone is not independent verification.
That production collector and price-increase experiments are not deployed yet.

## Price and capacity handoff

Use complete landed cost, taxes, fees and reserves to calculate the higher of
the 18% margin floor, C$8 profit floor and applicable MAP. Round upward to cents.
The catalogue queue intentionally does not invent missing checkout costs.
Start with quantity one per qualified SKU; preserve queue order while applying
fresh unit/value capacity and pending publication reservations. Do not pass a
raw screening candidate directly to a live publisher.

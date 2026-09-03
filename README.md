# Fire Finds — interim backend

Git repo tracking `https://github.com/clayyc2/fire-finds-backend`.
Python package lives under `backend/firefinds/`.

## Layout

```
firefinds/
  .env.example
  secrets/                 # mode 700 — never commit
  data/                    # SQLite / exports (gitignored)
  backend/firefinds/
    config.py
    db/schema.py           # products + ebay_competition + ranked_queue
    scoring/               # filters, shipping quotes, ids, dedupe, return-risk, competition
    clients/randmar.py     # catalog + read-only shipping quotes (never Process)
    clients/ebay.py        # Browse compete + gated Sell stubs
    listings/drafts.py     # Inventory API-shaped drafts (never publish)
    services.py            # ingest / score / rank
    services_queue.py      # validate ALL eligible → ranked queue
    services_quote.py      # checkpointed multi-dest quotes (p75)
    cli/main.py
  tests/
```

## Feature gates (default OFF)

| Variable | Default | Effect |
|----------|---------|--------|
| `LIVE_LISTINGS_ENABLED` | false | Sell inventory/offer/publish refuse |
| `EBAY_SANDBOX_PUBLISH_ENABLED` | false | Publish refused even in sandbox |
| `SUPPLIER_ORDERS_ENABLED` | false | Order / Cart Process refuse |
| `EBAY_PRODUCTION_ENABLED` | false | Production Sell gated |

## Shipping (hard rule)

**Do not treat $10 (or any marketing rate) as true shipping** unless the dealer
account/API confirms Fire Finds qualifies for that rate.

Final `listable_pass` / `final_profitability` require `shipping_status=RESOLVED`
from Randmar **read-only** quotes across representative Canadian destinations:

| City | Province | Postal |
|------|----------|--------|
| Calgary | AB | T2P 1J9 |
| Vancouver | BC | V6B 1A1 |
| Toronto | ON | M5H 2N2 |
| Montreal | QC | H3B 1A7 |
| Halifax | NS | B3J 1S9 |

Endpoints (never `Cart/Process*`):

- `POST .../Cart/ShippingMethods/{cartName}` (after AddItem)
- `POST .../ShippingLabel/Estimate`

`ShipToLocation` fields sent: Name, Street1, Street2 (may be empty), City,
Province (2-letter), PostalCode, Country (`CA`). OpenAPI marks them nullable
but Cart/ShippingMethods requires that subset (`additionalProperties: false`).

**Profitability shipping cost = 75th percentile** of resolved dest quotes for
that SKU (not mean, not min). Fewer than 5 resolved → p75 over whatever
resolved. **Zero resolved → `UNRESOLVED` → not finally profitable.**

SKUs whose $8 / 12% floors fail in expensive dests even when p75 passes are
flagged `fails_expensive_destinations=true` with the failing cities listed.
They can still rank on p75; the flag is a warning for far-coast buyers.

**Fulfillment will later use the buyer's actual postal code** for the real
quote. These five dests are screening proxies only.

If a quote cannot be obtained → `shipping_status=UNRESOLVED` → SKU is **not**
finally listable. `SHIP_EST_CAD` is only a rough early `score_pass` placeholder.
Per-dest rows persist in `shipping_quotes` (+ `data/shipping_quote_progress.json`
checkpoint). `quote-shipping --limit N` for tests; omit `--limit` for the full
eligible set. Resume is the default.

## Eligible → ranked queue (no hard SKU cap)

1. Load **all** eligible (`eligible=1` / `score_pass=1`, ~513 today)
2. Normalize UPC/MPN (checksum when possible)
3. Dedupe duplicate UPC or MPN+manufacturer (keep best stock/profit; log merges)
4. Return-risk / category deny-list exclusions
5. Resolve Randmar shipping quote (or UNRESOLVED)
6. eBay Browse competition when credentials exist; otherwise provisional flags
   (`provisional_public_ebay`, `needs_official_ebay_validation`) — pipeline continues
7. MAP floor: never price below MAP; `OpportunityOnly` hard-fails
8. Keep **every** SKU that passes; rank by
   `expected_monthly_contribution_profit * sales_probability` → `rank_score`
9. Persist `ranked_queue` + `data/ranked_queue.json`; draft listing JSON locally

## eBay

Developer approval may be pending. Without `EBAY_CLIENT_ID` +
`EBAY_CLIENT_SECRET_FILE`, `ebay-compete` / `validate-queue` skip official Browse
and flag rows for later validation. Sell stubs always refuse while listings gates
are off.

## CLI

```bash
cd /workspace/firefinds/backend
python -m pip install -e ".[dev]"
PYTHONPATH=. python -m firefinds.cli.main health
PYTHONPATH=. python -m firefinds.cli.main ingest-stub
PYTHONPATH=. python -m firefinds.cli.main ingest-live   # read-only
PYTHONPATH=. python -m firefinds.cli.main score
PYTHONPATH=. python -m firefinds.cli.main quote-shipping [--limit N] [--rebuild-queue]
PYTHONPATH=. python -m firefinds.cli.main validate-queue   # ALL eligible (p75 dest quotes)
PYTHONPATH=. python -m firefinds.cli.main ebay-compete     # alias
PYTHONPATH=. python -m firefinds.cli.main listable-export
PYTHONPATH=. python -m firefinds.cli.main ebay-sandbox-status
PYTHONPATH=. python -m firefinds.cli.main freeze-shipping-snapshot
PYTHONPATH=. python -m firefinds.cli.main split-cohorts --snapshot-id YYYYMMDD_HHMM
PYTHONPATH=. python -m firefinds.cli.main authorize-drafts --snapshot-id YYYYMMDD_HHMM
PYTHONPATH=. python -m firefinds.cli.main ebay-demand-discover --snapshot-id YYYYMMDD_HHMM
PYTHONPATH=. python -m firefinds.cli.main pipeline-freeze-split-draft
```

`--inject-ship CAD` is **test-only** to inject a resolved shipping cost. Production
must use Randmar quote endpoints.


## Dual pipelines

| Tag | Meaning |
|-----|---------|
| `pipeline_source=RANDMAR_FIRST` | Eligible Randmar catalog → shipping → competition → ranked |
| `pipeline_source=EBAY_DEMAND_FIRST` | Repeated eBay CA sold demand → catalog match → economics |

Cohorts: `SAFE_NATIONWIDE` (finally profitable, not destination-sensitive),
`DESTINATION_SENSITIVE` (`fails_expensive_destinations`), 
`QUARANTINE_UNRESOLVED` (unresolved shipping — never sellable).

Every candidate row carries `pipeline_source`, `cohort`, `comparison_cohort_id`,
and empty A/B metric columns (`sell_through`, `time_to_first_sale`,
`contribution_profit_realized`, `cancellations`, `returns`) for later comparison.

`EBAY_DEMAND_FIRST` is scaffolded with provisional public flags until official
eBay OAuth keys arrive (`EBAY_SELLING_LIMIT` is a soft placeholder only).

Drafts under `data/drafts/randmar_first/` are local Inventory API payloads —
**never published** while `LIVE_LISTINGS_ENABLED` / `EBAY_SANDBOX_PUBLISH_ENABLED`
remain false.

## Tests

```bash
cd /workspace/firefinds/backend
PYTHONPATH=. python -m pytest ../tests -q
```

## Safety

- Do **not** place supplier orders / Process carts.
- Do **not** publish eBay listings.
- Do **not** print secret or token values.
- Do **not** invent flat shipping as final cost.

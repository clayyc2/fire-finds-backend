# Fire Finds — interim backend scaffold

Greenfield local project at `/workspace/firefinds` (not an external git clone).
Python package lives under `backend/firefinds/`. Origin/repo wiring comes later.

## Layout

```
firefinds/
  .env.example          # documented env + feature gates (defaults OFF)
  .gitignore            # .env, secrets/, *.db, __pycache__, …
  secrets/              # mode 700 — Integration key files (never commit)
  data/                 # created at runtime (SQLite + actions.jsonl)
  backend/
    firefinds/
      config.py         # settings from env
      db/schema.py      # products + actions SQLite schema
      scoring/filters.py
      action_log/logger.py
      clients/randmar.py
      services.py       # ingest-stub / score / rank
      cli/main.py
  tests/
```

## Secrets

`RANDMAR_CLIENT_ID` and `RANDMAR_CLIENT_SECRET` come from the Randmar
**Integration key**. Put them in `/workspace/firefinds/secrets/` (files named
`client_id` / `client_secret`, or env vars). **Never commit** secrets. The
client stub loads them when present and never prints secret values.

## Feature gates (default OFF)

| Variable | Default | Effect |
|----------|---------|--------|
| `LIVE_LISTINGS_ENABLED` | false | Live listing pushes gated |
| `SUPPLIER_ORDERS_ENABLED` | false | Order methods raise `SupplierOrdersDisabled` |
| `EBAY_PRODUCTION_ENABLED` | false | Production eBay gated |

## Scoring filters (deterministic)

A product **passes** only when all hold:

1. `contribution_profit >= MIN_CONTRIBUTION_PROFIT_CAD` (default **8** CAD)
2. `contribution_margin >= MIN_CONTRIBUTION_MARGIN` (default **0.12**)
3. `stock > STOCK_BUFFER` (default **2**)

`contribution_profit = sell_price - landed_cost + rebate`  
`contribution_margin = contribution_profit / sell_price`  
Sell price prefers MAP, then MSRP. Landed cost prefers `landed_cost`, else `dealer_cost`.

Every decision is appended to `data/actions.jsonl` and the `actions` SQLite table.

## Setup

```bash
cd /workspace/firefinds/backend
python -m pip install -e ".[dev]"   # or: pip install pytest && PYTHONPATH=. …
cp ../.env.example ../.env          # edit locally; do not commit
```

## CLI

```bash
cd /workspace/firefinds/backend
PYTHONPATH=. python -m firefinds.cli.main ingest-stub
PYTHONPATH=. python -m firefinds.cli.main score
PYTHONPATH=. python -m firefinds.cli.main rank -n 10
```

Or after editable install: `firefinds ingest-stub|score|rank`.

## Tests

```bash
cd /workspace/firefinds/backend
PYTHONPATH=. python -m pytest ../tests -q
```

## Safety

- Do **not** place supplier orders with this scaffold; the order gate refuses by default.
- Do **not** print secret values.
- Live Randmar catalog fetch requires credentials; offline work uses `ingest-stub`.

# Fire Finds — interim backend

Git repo tracking `https://github.com/clayyc2/fire-finds-backend`.
Python package lives under `backend/firefinds/`.

## Layout

```
firefinds/
  .env.example          # CLIENT_ID + CLIENT_SECRET_FILE + feature gates
  .gitignore            # .env, secrets/, data/, *.db, …
  secrets/              # mode 700 — Integration key secret (never commit)
  data/                 # live dumps / SQLite (gitignored)
  backend/
    firefinds/
      config.py
      db/schema.py
      scoring/filters.py
      action_log/logger.py
      clients/randmar.py   # token + Products/JSON POST + InstantRebates GET
      services.py          # ingest-stub / ingest-live / score / rank
      cli/main.py
  tests/
```

## Secrets

- `Settings.from_env()` auto-loads `PROJECT_ROOT/.env` (does not override already-set env vars). Quote spaced values: `RANDMAR_CLIENT_ID="Fire Finds catalog read"`.
- `RANDMAR_CLIENT_ID` = Integration key **name**; defaults to `Fire Finds catalog read` when unset (also `secrets/randmar_client_id.txt`)
- `RANDMAR_CLIENT_SECRET_FILE` = path to secret file under `secrets/`
  (default `secrets/randmar_api_key.txt`)

Never commit `.env`, `secrets/`, `data/`, or `*.db`. The client never logs
secret or token values.

## Feature gates (default OFF)

| Variable | Default | Effect |
|----------|---------|--------|
| `LIVE_LISTINGS_ENABLED` | false | Live listing pushes gated |
| `SUPPLIER_ORDERS_ENABLED` | false | Order methods / `place-order` refuse |
| `EBAY_PRODUCTION_ENABLED` | false | Production eBay gated |

## Scoring filters (deterministic)

A product **passes** only when all hold:

1. `contribution_profit >= MIN_CONTRIBUTION_PROFIT_CAD` (default **8** CAD)
2. `contribution_margin >= MIN_CONTRIBUTION_MARGIN` (default **0.12**)
3. `stock > STOCK_BUFFER` (default **2**)

Sell price = **MAP** if MAP > 0, else **0.95 × MSRP**.

```
fees = sell * 0.1325 + 0.30
contribution_profit = sell - fees - 10 - landed_cost + rebate
contribution_margin = contribution_profit / sell
```

Landed cost prefers `landed_cost`, else `dealer_cost` (Randmar `Price`).

## Setup

```bash
cd /workspace/firefinds/backend
python -m pip install -e ".[dev]"
cp ../.env.example ../.env   # edit locally; do not commit
```

## CLI

```bash
cd /workspace/firefinds/backend
PYTHONPATH=. python -m firefinds.cli.main ingest-stub
PYTHONPATH=. python -m firefinds.cli.main ingest-live   # read-only live pull
PYTHONPATH=. python -m firefinds.cli.main score
PYTHONPATH=. python -m firefinds.cli.main rank -n 10
```

`place-order` refuses while `SUPPLIER_ORDERS_ENABLED=false`.

## Tests

```bash
cd /workspace/firefinds/backend
PYTHONPATH=. python -m pytest ../tests -q
```

## Safety

- Do **not** place supplier orders; the order gate refuses by default.
- Do **not** print secret or token values.
- `ingest-live` is catalog read-only (token + products POST + instant rebates GET).

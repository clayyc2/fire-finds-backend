# Ops exception engine (deterministic)

Small rule engine that **auto-flags / pauses** candidates and simulated
listings. No AI improvisation — each rule is a pure predicate over SKU fields
(or the actions log for ingest streak / open CS).

**Gates stay OFF** — scan never publishes listings or places supplier orders.

## Rules

| Code | Trigger | Default action |
|------|---------|----------------|
| `STOCK_LEQ_BUFFER` | `stock ≤ STOCK_BUFFER` (default 2) | pause |
| `SHIPPING_UNRESOLVED` | `shipping_status == UNRESOLVED` | pause |
| `PROFIT_BELOW_MIN` | listable/contribution profit &lt; `$8` CAD | pause |
| `MARGIN_BELOW_MIN` | listable/contribution margin &lt; `12%` | pause |
| `MAP_BREACH` | sell price &lt; MAP (or `map_ok=0`) | pause |
| `CHANNEL_AUTH_FAIL` | `channel_ok=0` / opportunity-only channel block | pause |
| `API_INGEST_FAILURE_STREAK` | trailing ingest actions failed ≥ N (default 3) | flag (global `__INGEST__`) |
| `COST_SPIKE` | `dealer_cost` (or `net_cost`) ↑ ≥ 10% vs `last_known_cost` | pause |
| `RETURNS_RATE_HIGH` | `returns / sales_units > 8%` with `sales_units ≥ 5` | pause |
| `CANCELLATION_RATE_HIGH` | `cancels / (sales+cancels) > 5%` with n ≥ 5 | pause (flag if non-seller `cancel_fault`) |
| `CS_EXCEPTION_OPEN` | open CS (`cs_open=1` or actions `cs_case`) ≥ 24h | flag |
| `ACCOUNT_HEALTH_RISK` | `account_defect_rate > 2%` / `policy_strike` / `selling_limit_hit` | flag (often sku `__ACCOUNT__`) |
| `TRACKING_MISSING` | `order_status` in `SIMULATED_ORDER`/`AWAITING_SHIP`, &gt;48h, no tracking | flag |
| `FULFILLMENT_LATE` | hours since order &gt; 72 and `ship_status != SHIPPED` | flag |
| `DUPLICATE_LISTING` | `active_offer_count > 1` | pause |
| `INVALID_LISTING` | `listing_validation_ok=0` / missing specifics / identity mismatch | pause |

Core economics thresholds come from Settings / env: `STOCK_BUFFER`,
`MIN_CONTRIBUTION_PROFIT_CAD`, `MIN_CONTRIBUTION_MARGIN`.

Unlock / CS / fulfillment thresholds are module constants in
`backend/firefinds/ops/exceptions.py` (10% cost spike, 8% returns, 5% cancels,
24h CS, 2% defect, 48h tracking, 72h fulfillment, duplicate max 1).

Row fields may also arrive via `detail_json` (flattened before evaluate).

## Persistence

- Table `ops_exceptions` (sku, rule_code, severity, status, message, detail_json, …)
- Append-only `actions` / JSONL via ActionLogger (`ops_exception`, `ops_pause`)
- Pause writes `products.paused=1`, `pause_reason`, `eligible=0`
- Global sentinels `__INGEST__` / `__ACCOUNT__` are never product-paused

## CLI

```bash
# via firefinds
firefinds ops-exceptions scan --snapshot-id 20260904_0140
firefinds ops-exceptions list
firefinds ops-exceptions rules

# standalone console script
ops-exceptions scan --snapshot-id 20260904_0140
ops-exceptions list --status open,paused
ops-exceptions list --rule STOCK_LEQ_BUFFER --sku ABC
```

`scan` never publishes listings or places supplier orders. Gates stay OFF.

## Spec / sims

- `data/ops/cs_exception_rules_spec.md` — rule table (proposed → landed)
- `data/ops/unlock_failure_sims.{json,md}` — offline failure sims (gates OFF)

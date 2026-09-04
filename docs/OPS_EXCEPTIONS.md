# Ops exception engine (deterministic)

Small rule engine that **auto-flags / pauses** candidates and simulated
listings. No AI improvisation — each rule is a pure predicate over SKU fields
(or the actions log for ingest streak).

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

Thresholds come from Settings / env: `STOCK_BUFFER`,
`MIN_CONTRIBUTION_PROFIT_CAD`, `MIN_CONTRIBUTION_MARGIN`.

## Persistence

- Table `ops_exceptions` (sku, rule_code, severity, status, message, detail_json, …)
- Append-only `actions` / JSONL via ActionLogger (`ops_exception`, `ops_pause`)
- Pause writes `products.paused=1`, `pause_reason`, `eligible=0`

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

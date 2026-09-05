# Local deterministic runner

This profile is **price preparation and order checking, not automatic supplier
purchasing or live listing publication**. The read-only adapters structurally
refuse commerce writes even if ambient environment flags attempt to enable them.
No AI, Grok, browser session or active chat is needed to execute a cycle.

```sh
python3 scripts/run_operations.py --secrets-dir secrets \
  --mapping data/fulfillment-readiness/verified_sku_mapping.json \
  --purchase-audit data/supplier-readiness/listed-buyability.json \
  --out data/operations --environment production --reseller-id 2WQN9V11G
```

Each cycle checks own eBay orders through the existing connected worker.
Without verified buyer checkout evidence it explicitly reports orders HELD;
an order number is never represented as paid supplier fulfillment. Independently,
it refreshes the Randmar catalogue hourly and rebuilds the full opinion-ranked,
starting-priced candidate queue. A failed catalogue request does not skip order
checks. No external market research is performed. Catalogue, pricing, attention
and completion checkpoints are atomic/private; overlapping cycles serialize.
An old output file is not evidence of a successful fresh cycle: inspect
`status.json` timestamps and errors, and the catalogue observation timestamp.

`data/operations/attention.json` is a LOCAL durable alert, not an externally
delivered notification. Live launch still requires delivered alerts, backups,
supplier payment/reconciliation, full buyer checkout evidence and E2E acceptance.

## macOS installation

`deploy/store.firefinds.runner.plist` is a prepared LaunchAgent for this exact
workspace and `/usr/bin/python3`, every five minutes. No secrets appear in it.
It is not installed merely because the template exists. Installation requires
write access to the exact user LaunchAgents file and registering the job;
verify a successful scheduler-run status afterward. The initial filesystem
permission request did NOT grant that write access. The user then explicitly
approved installation, but a second request still returned no filesystem grant.
The job remains uninstalled; this is a system permission boundary, not a missing
user authorization. Do not bypass this by
registering a different persistent service without the requested permission.

The user's Mac must be awake, logged in and online. This is not a 24/7 hosted
service; it cannot satisfy continuous fulfillment while the Mac sleeps or is
off. Do not change sleep settings silently or claim a cloud deployment exists.
Uninstalling the exact LaunchAgent and unregistering its label stops future
runs without deleting the operational data or secrets. Rotate the local logs
before enabling long-running production commerce.

## Starting-price assumptions

All 4,503 currently eligible screening candidates have concrete starting item
prices and a separate buyer shipping charge. A known weight <= 2 lb uses a
C$49.95 shipping allowance; heavier/unknown weight uses C$99.95. Costs include
20% supplier-cost contingency, an estimated fee rate of at least 20% on a
120% revenue basis, C$0.50 fixed fee and 5% return reserve. These are deliberate
business estimates, NOT verified shipping maxima, tax rates or platform fees.
Both the 18% contribution margin and C$8 contribution-profit minimum apply
after these estimates. Item-only MAP is checked separately from shipping.

Example: SKU 5090907 starts at C$88.05 + C$49.95 shipping = C$138 before buyer
tax. This is intentionally expensive under the high-allowance approach and may
reduce sales. No competitor price was checked. Actual costs exceeding the
allowances could still reduce profit; the buyer-specific fulfillment check
must use fresh actual quotes and complete costs, not relabel estimates as proof.

All controls live in `Settings` and `.env.example`; scripts never source `.env`.
Set explicit process environment values to override assumptions. Starting-price
changes only update local planning output; they do not reprice existing eBay
offers or authorize any new listing.

## Verified execution checkpoint

A foreground production cycle completed successfully at Unix time
1788644868.576077, refreshing all 19,583 catalogue products, preparing 4,503
starting-priced candidates and checking the account's order window (zero orders).
No commerce writes occurred. This proves that the local cycle can execute; it
does NOT prove background registration, continuous availability or supplier
purchasing. Full test suite: 492 passed. Scheduler template passed `plutil -lint`.

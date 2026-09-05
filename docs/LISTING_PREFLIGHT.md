# Catalogue expansion — 2026-09-05

**No new listings published. No supplier orders submitted.** All commerce
gates remain off. The latest instruction removes market research and competitor
checks, not fulfillment, channel, shipping or profit safeguards.

## Completed this checkpoint

- Processed all **19,583** catalogue records offline, without market research.
- Prepared **4,503** opinion-ranked candidates; **15,080** held/existing records.
- **Zero fully publication-ready products.** Candidate does not mean qualified.
- Default initial quantity: one per eligible SKU, with a two-unit supplier
  stock buffer. Price must meet 18% margin, C$8 profit and MAP after complete
  costs. Initially prices were unset. The follow-up below now assigns concrete
  starting prices using explicitly labeled conservative estimates.
- First five candidates: Brother `5090907`, `5090692`, `5090666`, then Canon
  `CANCLI281B`, `CANCLI281C`. Fresh Product GETs at approximately **21:16 UTC**
  confirmed all five buyable, not opportunity-only, with stock above buffer.
  This does not establish eBay channel permission or complete economics.
- Real non-purchasing quote check for `5090907`: cheapest services at sample
  Calgary/Toronto destinations C$10, Vancouver/Montreal C$12.37, Halifax C$15.88.
  The owned quote cart was deleted successfully. These are not nationwide
  shipping coverage, final tax-inclusive totals or delivery guarantees.
- Own-account remaining capacity at approximately **21:16 UTC**:
  **4,952 units / CAD 60,753.98**, from successful official
  `GetMyeBaySelling` summary, not an assumed subtraction from headline limits.
  This is an expired planning observation, NOT a current reservation.
- Browse/competition entry points now refuse network access by default;
  cached comparables do not affect deterministic-engine price or score.
- Removed a legacy authorization shortcut that confused supplier buyability
  with eBay channel permission. Missing explicit evidence now holds the SKU.
- Full suite: **449 passed**. Real purchasing/fulfillment acceptance is NOT
  certified by these unit and fake-adapter tests.

## Why publication is still held

1. Resolve manufacturer/product eBay permission, media usage and return policy.
2. Confirm unattended supplier payment and paid order release for this account.
3. Complete item/destination shipping, tax/fee bounds and service promises.
4. Complete real-response Sandbox/dry-run lifecycle acceptance and production
   evidence collection; fake purchases/shipments are insufficient.
5. Deploy the deterministic runner, operational alerts and shared durable
   publication reservations. The live publication loop is not deployed.

Market research is **not** a launch requirement under the revised policy.
Initial ranking is expressly opinion, then only Fire Finds' own results may
inform performance-based reordering or price increases.

Immediately before each publication batch, refresh official remaining quantity
and value (60-second maximum age), subtract pending reservations, and apply all
item readiness checks. Stop when either allowance is exhausted; unknown or
stale capacity must never be treated as unlimited. Screening candidates may
not bypass these checks simply because there is spare account allowance.

Private evidence (Git-ignored): `data/listing-preflight/` including
`opinion-catalogue-queue.json`, `opinion-first-products.json`,
`opinion-first-quote/` and `opinion-remaining-capacity.json`.
See [operating policy](OPERATING_POLICY.md), [queue runbook](CATALOGUE_QUEUE.md)
and [supplier readiness](SUPPLIER_READINESS.md).

## Conservative-pricing and runner follow-up

The user explicitly authorized high shipping estimates rather than waiting for
quotes. All **4,503** screening candidates now have concrete item prices plus
separate shipping charges, using C$49.95 for known <=2 lb weight or C$99.95 for
heavier/unknown weight, with configurable supplier-cost, fee and return reserves.
The 18%/C$8 floors apply after those estimates, and MAP applies to item price.
These estimates are not verified shipping maxima or guaranteed profits.

Private output: `data/listing-preflight/priced-catalogue-queue.json`. A successful
foreground production runner cycle also refreshed supplier data and generated
`data/operations/starting-prices.json`, with zero recent orders returned.
No new publication or supplier purchase occurred. **492 tests pass.**

The background scheduler is prepared but NOT installed: the system returned no
filesystem grant even after the user explicitly approved the exact LaunchAgent.
Automatic purchasing remains unimplemented in this deployed-profile candidate;
it runs the existing worker with read-only adapters and reports held orders.
See [local runner](LOCAL_RUNNER.md) for exact state, assumptions and limits.

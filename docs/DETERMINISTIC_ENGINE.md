# Deterministic engine architecture

The execution path is intentionally rules-based. AI/Grok may propose research
signals, but those signals must enter as ordinary data and cannot publish,
reprice, reserve capacity, or place an order.

1. **Randmar Importer** normalizes catalog, price, stock and supported shipping
   data into candidates.
2. **Opportunity Engine** fail-closes on channel/MAP permission, unresolved
   shipping, stock buffer, return risk, profit and margin floors; it computes a
   reproducible target price and weighted rank.
3. **Capacity Manager** selects ranked candidates while reserving configured
   headroom below both monthly item and value limits.
4. **Repricer** reruns the same gates whenever supplier price, stock, shipping,
   or competition changes.
5. **Order Router** deduplicates paid orders and refuses supplier submission in
   dry-run, with the global kill switch on, or while supplier ordering is off.
   It reads paid eBay orders and existing fulfillments through the official
   Fulfillment API. Tracking submission has a separate default-off
   `EBAY_TRACKING_UPDATES_ENABLED` gate, plus dry-run and the global kill switch.
6. **Discovery/Refresh Engine** composes import, evaluation and capacity into a
   repeatable refresh pass.

Every boundary emits JSONL audit events. Retry helpers use bounded exponential
backoff; idempotency keys are deterministic. Existing eBay and Randmar clients
remain the only integration boundaries. Live publishing and supplier ordering
remain disabled by default.

## Launch-readiness checklist

- [ ] Full unit suite passes in a clean environment.
- [ ] Recorded Randmar import/price/stock/shipping fixtures pass.
- [ ] MAP and channel permissions are complete for every candidate.
- [ ] All listable SKUs have resolved shipping and stock-buffer coverage.
- [ ] eBay Sandbox inventory, offer, order and fulfillment lifecycle passes.
- [ ] Duplicate webhook/order replay produces exactly one simulated order.
- [ ] Rate-limit, timeout, retry exhaustion and checkpoint-resume tests pass.
- [ ] Item and value capacity remain below configured headroom under replay.
- [ ] Repricing never crosses MAP, margin or absolute-profit floors.
- [ ] Kill-switch tests prove all external mutations are refused.
- [ ] Audit log reconciles every decision and state transition.
- [ ] Legal/compliance approval for brands, channels, returns and customer data.
- [ ] Explicit human approval before enabling Sandbox publish.
- [ ] Separate explicit human approval before any production listing or supplier order.

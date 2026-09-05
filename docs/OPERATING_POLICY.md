# Clay's operating policy — 2026-09-05

This records the user's latest instructions, superseding earlier advice to
discard an otherwise eligible product solely because its safe price is above
competition. It does not enable any live gate by itself.

## Price

Use the higher of (a) a verified comparable competitor's price less the
configurable undercut, and (b) the price required by all profit and MAP floors.
Default undercut: C$0.01. Comparisons must use matching product, condition,
availability, market/currency and delivered-price basis; exclude Fire Finds'
own offers and unresolved/stale evidence. The evidence provider is still work
to complete; a numeric candidate field alone is not verified market evidence.

Both minimums apply: 18% contribution margin on revenue and C$8 contribution
profit per order, after relevant costs, fees, shipping and returns allowance.
Eighteen percent is a floor, not a ceiling: keep additional profit when market
pricing supports it. MAP can force a higher price. If competitors are cheaper
than the floor, offer at the floor instead of selling below it. Such items may
rank lower for demand, but price competitiveness alone no longer rejects them.

For an already-paid order, fulfillment checks the safe profit floor, not a
competitor's newly increased asking price. No retrospective repricing of orders.

## Supplier cash

Maximum C$2,500 authorized supplier spend per Edmonton calendar day. Reserve
the full supplier charge upper bound, including shipping and taxes (including
recoverable tax, which still consumes cash), before submitting a purchase.
This is separate from profit accounting and excludes eBay's platform fees,
which remain included in profit calculations.

The shared durable ledger counts completed and in-flight authorizations. Unknown
outcomes retain their reservation across midnight/restarts until reconciled;
never free budget merely because a request timed out. Cross-midnight completion
or reconciliation conservatively counts both involved dates. No automatic
refund/release is implemented. All workers must share the same ledger; existing
manual or other-channel supplier spend must also be reconciled before live use.

At the cap, hold additional purchases for a fresh check later; do not silently
overspend or cancel buyers' orders. Deployment must route these holds to an
operational alert and preserve eBay handling-time commitments. The current
read-only check reports holds; alert delivery/scheduling are not deployed yet.

## Autonomy and activation

Use deterministic scheduled software for import, ranking, capacity allocation,
listing, repricing, order routing and tracking. AI is not required in the
operating loop. Rank available inventory by likelihood of selling using
attributable evidence, then list fulfillment-ready eligible products up to
verified remaining eBay limits, accounting for pending reservations.

Clay conditionally authorized automatic fulfillment to activate as soon as it
is ready. Record a readiness evaluation before activation; this is not approval
to skip end-to-end testing, shipping resolution, channel permission, stock/MAP
checks or the cash/profit limits. No new activation approval is needed merely
to repeat that same instruction, but a materially different risk/spend scope
still requires direction. At this checkpoint live commerce gates remain OFF.

Config schema: `Settings` / `.env.example` — `TARGET_PROFIT_PCT=0.18`,
`MIN_CONTRIBUTION_MARGIN=0.18`, `MIN_CONTRIBUTION_PROFIT_CAD=8`,
`COMPETITOR_UNDERCUT_CAD=0.01`, `DAILY_SUPPLIER_SPEND_LIMIT_CAD=2500`,
`SUPPLIER_SPEND_TIMEZONE=America/Edmonton`.

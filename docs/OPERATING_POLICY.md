# Clay's operating policy — 2026-09-05

This records the user's latest instructions: NO market research or competitor
price checks. It supersedes the earlier competition-led pricing and externally
validated demand requirements. It does not enable any live gate by itself.

## Price

Start at the price required by the profit and MAP floors below, rounded UP to
the next cent. Do not fetch or use competitor comparables, including cached
comparables. The user referred to the previously agreed economics as markup;
the actual agreed rule remains contribution margin, not a cost markup.

Both minimums apply: 18% contribution margin on revenue and C$8 contribution
profit per order, after relevant costs, fees, shipping and returns allowance.
Eighteen percent is a floor, not a ceiling. MAP can force a higher price. Only
Fire Finds' own results may inform subsequent discretionary price increases;
an automatic price-experiment controller is not deployed yet. Supplier cost
increases must still trigger fresh floor calculations or a hold.

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
operating loop. Initially prioritize repeat-use consumables, affordable/light
products and buffered stock using catalogue-based opinion only. This is NOT a
measured probability of sale. Do not use supplier sales percentiles, external
sales data or competitor prices. Only attributable Fire Finds results may
subsequently reorder this queue. Begin with one unit per qualified SKU to test
more distinct products, then list in queue order up to both verified remaining
eBay limits, accounting for pending reservations. See `CATALOGUE_QUEUE.md`.

Clay conditionally authorized automatic fulfillment to activate as soon as it
is ready. Record a readiness evaluation before activation; this is not approval
to skip end-to-end testing, shipping resolution, channel permission, stock/MAP
checks or the cash/profit limits. No new activation approval is needed merely
to repeat that same instruction, but a materially different risk/spend scope
still requires direction. At this checkpoint live commerce gates remain OFF.

Config schema: `Settings` / `.env.example` — `TARGET_PROFIT_PCT=0.18`,
`MIN_CONTRIBUTION_MARGIN=0.18`, `MIN_CONTRIBUTION_PROFIT_CAD=8`,
`MARKET_RESEARCH_ENABLED=false`, `INITIAL_LISTING_QUANTITY=1`,
`DAILY_SUPPLIER_SPEND_LIMIT_CAD=2500`,
`SUPPLIER_SPEND_TIMEZONE=America/Edmonton`.

Legacy comparable functions remain available for compatibility but their
network entry points are disabled by default. Do not opt them in under the
current operating policy. Synthetic tests make no market research requests.

## Latest instruction: publish without waiting for supplier replies

The user confirmed the setup email was sent and explicitly requested immediate
publication, accepting business risk rather than awaiting supplier replies.
Do not ask the user to repeat publication authorization or treat a pending
email reply as the only blocker. This request is not factual evidence of
supplier eligibility, checkout costs or a working fulfillment deployment, and
does not authorize false product/shipping claims or acceptance of new supplier
terms. At this checkpoint all 4,503 screening candidates lack finalized
listing prices and the automatic fulfillment deployment remains incomplete.
No actual publication has occurred.

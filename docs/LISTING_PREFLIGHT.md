# Requested catalogue expansion — 2026-09-05

**No new listings published.** The request authorizes listing qualified items;
it does not supply missing fulfillment, channel, economics or demand evidence.

Latest follow-up: [supplier readiness](SUPPLIER_READINESS.md) records actual
Product/cart/shipping checks, the completed business contact profile, and two
existing HP SKUs that Randmar does not allow this account to purchase.

Independent production reads at approximately 20:13–20:15 UTC:

- Account cap: 5,000 units / CAD 69,515.02.
- Actual remaining allowance: **4,952 units / CAD 60,753.98**.
- Source: successful official `GetMyeBaySelling` summary, not subtraction from
  an assumed inventory count. Both limits constrain additional listings.
- Zero recent orders returned by the Account-readiness order check.
- All commerce-write gates remain off.

The [official eBay guidance](https://www.developer.ebay.com/support/knowledge-base/5198)
distinguishes remaining allowance from headline limits. The new fixed read-only
client method and parser preserve that distinction, reject incomplete/non-CAD
responses, and expire planning snapshots after 60 seconds. Pending publication
reservations must be subtracted; a shared publication ledger is still required.

## Why publication is held

1. No production item has completed unattended fulfillment readiness. The
   connected worker and 334-test milestone use fake purchases/shipments; the
   live evidence collector and always-on deployment remain incomplete.
2. All 19,583 catalogue products have NOT been ranked by verified probability
   of selling on eBay. There is a legacy supplier-first shortlist and isolated
   research, not a complete validated eBay demand-ranked catalogue.
3. The inherited demand-compatible report has 15 held candidates, zero ready.
   Another pilot mixes genuine and compatible toner titles and repeated rows;
   these cannot be treated as clean, deduplicated sold-demand evidence.
4. Item-level shipping, channel/return policy and complete economics must be
   resolved before qualification. Current identity matches for 48 live listings
   do not authorize expanding to the entire supplier catalogue.

Private diagnostic evidence: `data/listing-preflight/`. The earlier shortlist
and source reports remain preserved, not promoted to live eligibility. The next
publication batch must be built from qualified records, ordered by attributable
eBay-demand evidence, with profit and supplier-cash policy applied. It must stop
when either remaining allowance is exhausted, and never treat unknown capacity
as unlimited. No claim is made that this publication loop is deployed yet.

# Fire Finds AI organization

How autonomous agents collaborate on catalog research, listing creative, and
day-to-day ops — and how the **interim backend** remains the authority that can
block or override any AI proposal.

Ops coordination channel: **Fire Finds Ops**.

## Roles

| Role | Mandate |
|------|---------|
| **CTO (orchestrator)** | Routes work across agents, keeps shared SKU state coherent, decides when to escalate, never bypasses backend gates. |
| **Product Research** | Discovers demand and supplier fit (`RANDMAR_FIRST` / `EBAY_DEMAND_FIRST`), proposes matches, economics, and cohort placement. |
| **Listing & Creative** | Builds draft Inventory payloads and creative variants (original vs AI-enhanced thumbs); never publishes. |
| **Operations** | Runs queues, quotes, freezes, cohort splits, and draft authorization; watches gates and escalates failures. |

All roles read and write through the **shared SKU record**. No agent invents a
parallel source of truth.

## Source of truth

- The backend **SKU / product + ranked_queue / cohort** records are canonical.
- AI agents may propose fields (title, price band, match class, creative URLs,
  notes) but **backend feature gates override AI**.
- Soft proposals that conflict with gates (`LIVE_LISTINGS_ENABLED`,
  `EBAY_SANDBOX_PUBLISH_ENABLED`, `SUPPLIER_ORDERS_ENABLED`,
  `EBAY_PRODUCTION_ENABLED`) are refused — AI cannot flip those flags.

## Pipelines

| Tag | Flow |
|-----|------|
| `RANDMAR_FIRST` | Eligible Randmar catalog → shipping (p75) → competition → rank → cohorts → draft authorize |
| `EBAY_DEMAND_FIRST` | Repeated eBay CA sold/active demand → catalog match → economics → authorize → rank |

Both pipelines tag candidates with `pipeline_source`, `cohort`
(`SAFE_NATIONWIDE` / `DESTINATION_SENSITIVE` / `QUARANTINE_UNRESOLVED`), and
empty A/B metric columns for later comparison. See root `README.md` Dual
pipelines.

## Match classes (demand ↔ catalog)

When linking eBay demand to Randmar SKUs, Product Research assigns one of:

| Class | Meaning | Auto-link? |
|-------|---------|------------|
| `A_EXACT` | Exact UPC, or exact MPN + manufacturer (canonicalized) | Yes — preferred |
| `B_VARIANT` | Controlled variant: exact MPN + manufacturer, model token equality when both sides have a model | Yes — narrow only |
| `C_SUBSTITUTE` | Functional substitute / related SKU (different UPC/MPN) | **No** — escalate; do not auto-link |

Implementation today maps `A_EXACT` → `exact_upc` / `exact_mpn_manufacturer`,
`B_VARIANT` → `controlled_variant`. Anything else is `no_match` until a human
(or explicit `C_SUBSTITUTE` review) decides. No fuzzy edit-distance, title
substring, or brand-only matching.

## Creative A/B

Listing & Creative may prepare two thumb/creative treatments per authorized
draft SKU:

| Arm | Content |
|-----|---------|
| **A — original** | Supplier / catalog imagery and copy as-is (normalized for eBay Inventory shape) |
| **B — AI-enhanced** | AI-improved thumbs / lighting / crop / listing copy; same SKU identity and facts |

A/B is for **draft comparison and later sell-through metrics only**. Neither arm
is published while listings gates are OFF. Metric columns
(`sell_through`, `time_to_first_sale`, `contribution_profit_realized`,
`cancellations`, `returns`) stay empty until live comparison is explicitly
authorized.

## Safety (hard)

Until **full E2E validation** and **explicit human authorization**:

- eBay **listings / publish** remain **OFF**
  (`LIVE_LISTINGS_ENABLED`, `EBAY_SANDBOX_PUBLISH_ENABLED`,
  `EBAY_PRODUCTION_ENABLED` default false).
- Supplier **orders / Cart Process** remain **OFF**
  (`SUPPLIER_ORDERS_ENABLED` default false).
- Agents write **local drafts** only (`data/drafts/…`); never Process carts;
  never invent flat shipping as final cost; never print secrets or tokens.

Backend stubs refuse gated Sell / Process calls regardless of AI intent.

## Escalation path

Escalate to a **human** (Clay / Fire Finds Ops) when any of the following hold:

1. Match would be `C_SUBSTITUTE`, ambiguous multi-hit catalog, or conflicting IDs.
2. Shipping stays `UNRESOLVED` / quarantine after retries, or destination-sensitive
   economics look wrong for a intended nationwide listing.
3. Gate refusal, credential / OAuth gaps, or provisional eBay flags that block
   official validation.
4. Creative A/B would change factual claims (specs, UPC, MAP, price below MAP).
5. Any request to enable live listings or place supplier orders.
6. Unexpected losses, cancellations, MAP/opportunity-only conflicts, or policy risk.

Escalation channel: **Fire Finds Ops**. Include SKU, pipeline_source, cohort,
match class, gate state, and a one-line ask. Do not ask the channel to bypass
gates in chat — flip gates only via explicit env / human change after E2E.

## Channel

**Fire Finds Ops** — day-to-day coordination for research findings, draft
ready-for-review notices, quarantine summaries, and human escalations.

# eBay unlock checklist

Gates stay **OFF** until each stage below is explicitly completed and human-approved.
Default: `LIVE_LISTINGS_ENABLED=false`, `EBAY_SANDBOX_PUBLISH_ENABLED=false`,
`EBAY_PRODUCTION_ENABLED=false`, `SUPPLIER_ORDERS_ENABLED=false`.

This checklist unlocks **eBay Sell publish** only. Supplier Cart/Process remains a
separate unlock and is out of scope here.

## 0. Preconditions (ready-to-list backlog)

- [ ] `RANDMAR_FIRST / SAFE_NATIONWIDE` queue frozen and prioritized
- [ ] `RANDMAR_FIRST / DESTINATION_SENSITIVE` kept **separate** (do not mix into nationwide wave)
- [ ] `QUARANTINE_UNRESOLVED` excluded from any live wave
- [ ] `EBAY_DEMAND_FIRST` remains scaffold / provisional until official validation
- [ ] Drafts exist under `data/drafts/randmar_first/safe_nationwide/` (and
      `destination_sensitive/` only if intentionally included)
- [ ] Creative A/B metadata present (`ORIGINAL_SUPPLIER` / `AI_ENHANCED`) on SKU records
- [ ] Dry-run E2E (`dry-run-sku`) passes for sample SAFE_NATIONWIDE SKUs

## 1. OAuth

- [ ] eBay developer application approved for the needed scopes
- [ ] `EBAY_CLIENT_ID` set in env
- [ ] `EBAY_CLIENT_SECRET_FILE` points at a mode-600 secret file (never commit)
- [ ] User / refresh token flow completed for the selling account (CA marketplace)
- [ ] Token refresh path verified without printing secrets
- [ ] Confirm Browse (read) works before enabling any Sell write scopes in automation

**Exit criteria:** official Browse competition no longer needs
`provisional_public_ebay` / `needs_official_ebay_validation` for the pilot SKUs.

## 2. Sandbox / API validation

- [ ] Inventory API create/update inventory item against **sandbox** only
- [ ] Offer create/update against sandbox only
- [ ] Policy IDs (fulfillment / payment / return) resolved for sandbox
- [ ] MAP floor + stock buffer + shipping RESOLVED re-checked in backend gates
- [ ] Publish stub still refused while `EBAY_SANDBOX_PUBLISH_ENABLED=false`
- [ ] Flip `EBAY_SANDBOX_PUBLISH_ENABLED=true` **only** for a named sandbox SKU set
- [ ] Sandbox publish → verify listing shape → unpublish / clean up
- [ ] Re-set `EBAY_SANDBOX_PUBLISH_ENABLED=false` after validation
- [ ] No supplier Process / orders during this stage

**Exit criteria:** sandbox publish/unpublish succeeds for ≥1 SAFE_NATIONWIDE draft;
gates restored OFF; action log shows no production Sell calls.

## 3. Small controlled live wave

- [ ] Human written approval in **Fire Finds Ops** (SKU list + date + owner)
- [ ] Wave limited to **SAFE_NATIONWIDE** only (exclude DESTINATION_SENSITIVE + quarantine)
- [ ] Soft respect `EBAY_SELLING_LIMIT` / account selling limits
- [ ] Enable `LIVE_LISTINGS_ENABLED=true` (and production flag only if required) for the wave window
- [ ] Publish the approved SKU list only — no bulk of entire backlog
- [ ] Immediately confirm listings visible on eBay CA as expected (price ≥ MAP)
- [ ] Keep `SUPPLIER_ORDERS_ENABLED=false` until fulfillment path is separately approved

**Exit criteria:** N≪backlog live listings (recommend start with 1–5 SKUs); no MAP
or policy incidents; rollback plan ready (end listings / disable gate).

## 4. Measure

- [ ] Record marketplace metrics on shared SKU records: impressions, CTR,
      conversion_rate, sales_units, time_to_first_sale, sell_through,
      contribution_profit_realized, cancellations, returns
- [ ] Compare creative arms via `comparison_cohort_id` + `sku-record export-learning`
- [ ] Watch destination-sensitive economics separately if any far-coast orders appear
- [ ] Pause SKUs on gate failure, MAP conflict, or abnormal cancel/return rates

**Exit criteria:** enough data to judge whether to expand, retarget creative, or stop.

## 5. Scale

- [ ] Human approval to expand SKU count and/or include carefully reviewed
      DESTINATION_SENSITIVE (never quarantine)
- [ ] Raise selling limits with eBay if needed before expanding
- [ ] Keep cohort exports/queues separated; do not flatten SAFE + SENSITIVE
- [ ] Only then consider supplier-order unlock under its own checklist
- [ ] Document lessons in Fire Finds Ops and update this file if process changes

**Exit criteria:** repeatable wave playbook; gates still flipped deliberately per wave,
not left permanently ON by accident.

## Rollback (any stage)

1. Set all listing gates back to `false`
2. End or unpublish affected listings via eBay seller tools / Sell API
3. Mark SKUs paused in backend; log reason in actions JSONL
4. Escalate to Fire Finds Ops with SKU list + stage + failure note

## Related

- [`AI_ORG.md`](AI_ORG.md) — roles, match classes, creative A/B, escalation
- Root `README.md` — feature gates, dual pipelines, CLI
- CLI: `split-cohorts`, `authorize-drafts`, `batch-creative-drafts`,
  `ebay-demand-ingest`, `dry-run-sku`, `health`

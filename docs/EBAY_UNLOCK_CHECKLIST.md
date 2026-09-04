# eBay unlock checklist

> **Current stage (2026-09-04):** **Stage 0 ready / Stage-2 prep** — live freeze **`20260904_1348`** (post Band-A Browse keep): SAFE **127** / DEST **25** / QUAR **85** / ranked listable **152**. Prior `20260904_1311` SAFE 124 / DEST 25 / QUAR 101 / ranked 149. Prior freezes `20260904_1224` / `0140` / `1744` superseded for live ops. SAFE drafts + ORIGINAL_SUPPLIER creative present; quarantine excluded; gates **OFF**.  
> **Sandbox Final 5 (pack v2.1):** competitive-at-MAP **SAFE**; dry-runs **5/5 PASS** — `data/reports/sandbox_pack_v2_dry_runs.md` (+ `sandbox_pilot_pack_v2.*`).  
> **First-wave 25:** dry-runs **25/25 PASS** on `20260904_1311` — `data/reports/first_wave_25_dry_runs_20260904_1311.md` (+ `.json`). Wave playbook: `docs/STAGE2_WAVE_SIZING_PLAYBOOK.md`.  
> **Blocked on:** §2 offer — eBay **25709** Invalid categoryId (placeholder); then Business Policy / sellerRegistrationCompleted → Clay sandbox publish. §1b OAuth **done**. Gates stay OFF.  
> Gates stay OFF. Official Browse CA compete already applied (listable 335→149); fee/Store readiness: `data/reports/ebay_ca_fee_model_149_book.md`.

Gates stay **OFF** until each stage below is explicitly completed and human-approved.
Default: `LIVE_LISTINGS_ENABLED=false`, `EBAY_SANDBOX_PUBLISH_ENABLED=false`,
`EBAY_PRODUCTION_ENABLED=false`, `SUPPLIER_ORDERS_ENABLED=false`.

This checklist unlocks **eBay Sell publish** only. Supplier Cart/Process remains a
separate unlock and is out of scope here.

## 0. Preconditions (ready-to-list backlog)

- [x] `RANDMAR_FIRST / SAFE_NATIONWIDE` queue frozen and prioritized (`20260904_1348`, **127** SKUs; prior `20260904_1311` had 124; `20260904_1224` had 289; `20260904_0140` had 275; `20260903_1744` had 254)
- [x] `RANDMAR_FIRST / DESTINATION_SENSITIVE` kept **separate** (do not mix into nationwide wave) (**25** SKUs on `20260904_1348` / `20260904_1311`; was 46 on `20260904_1224`)
- [x] `QUARANTINE_UNRESOLVED` excluded from any live wave (**85** SKUs on `20260904_1348`; was 101 on `20260904_1311` / `1224`; 113 on `20260904_0140` / 140 on `20260903_1744`; recovery shortlist is ops-only)
- [x] Ranked listable / finally profitable post Band-A Browse keep: **152** (`20260904_1348`; was 149 on `20260904_1311`)
- [x] `EBAY_DEMAND_FIRST` remains scaffold / provisional until official validation
- [x] Drafts exist under `data/drafts/randmar_first/safe_nationwide/` (and
      `destination_sensitive/` only if intentionally included)
- [x] Creative A/B metadata present (`ORIGINAL_SUPPLIER` on SAFE survivors; AI_ENHANCED waves optional)
- [x] Dry-run E2E (`dry-run-sku`) passes for sandbox Final 5 v2.1 (**5/5 PASS**; see `data/reports/sandbox_pack_v2_dry_runs.md`) and first-wave 25 (**25/25 PASS**; see `data/reports/first_wave_25_dry_runs_20260904_1311.md`); historical v1: `sandbox_pack_dry_runs_20260904.md`

## 1. OAuth

> **Status:** Sandbox **client-credentials** (Browse app token) works. Sell **user**
> OAuth (authorization code → refresh token) **complete** for sandbox — refresh
> token stored locally (mode 600). Do **not** flip any Sell/publish gates yet.
> Secrets stay in env / `secrets/` (never commit).

### 1a. App credentials (client credentials — Browse)

- [x] Sandbox App ID / Cert ID present (client-credentials token works)
- [ ] `EBAY_CLIENT_ID` set in env (sandbox App ID)
- [ ] `EBAY_CLIENT_SECRET_FILE` points at a mode-600 secret file (never commit)
- [ ] Confirm Browse (read) works before enabling any Sell write scopes in automation

### 1b. RuName + Sell user OAuth (authorization code grant)

eBay does **not** use a normal HTTPS callback for the `redirect_uri` parameter —
you paste the **RuName** (eBay Redirect URL name) generated in the Developer Portal.

**Create a Sandbox RuName (Clay):**

1. Open [eBay Developer Portal → Application Keys](https://developer.ebay.com/my/keys) and select the **Sandbox** keyset.
2. Under **User Tokens** / **Get a Token from eBay via Your Application**, click to
   create / configure an OAuth redirect.
3. Fill the branding / privacy / auth-accepted URL fields (for local/dev you can use
   a simple HTTPS page or `https://localhost` / a placeholder you control — eBay still
   issues a **RuName** string such as `YourApp-YourApp-SBX-xxxxx`).
4. Copy the **RuName** value shown under **RuName (eBay Redirect URL name)**.
5. Paste into `.env` as **either**:
   - `EBAY_RUNAME=<RuName>` **or**
   - `EBAY_REDIRECT_URI=<RuName>` (alias — same value; do **not** invent a random URL)
6. Keep `EBAY_ENV=sandbox`. Optional override:
   `EBAY_USER_REFRESH_TOKEN_FILE=secrets/ebay_user_refresh_token.txt`

**Minimal Sell scopes** (marketing omitted — not required for inventory/offers):

- `https://api.ebay.com/oauth/api_scope/sell.inventory`
- `https://api.ebay.com/oauth/api_scope/sell.account`
- `https://api.ebay.com/oauth/api_scope/sell.fulfillment`

**CLI flow (secrets never printed):**

```bash
firefinds ebay-oauth-url          # open URL; sign in as Sandbox seller test user
# After Agree, browser lands on your Auth Accepted URL with ?code=...
# Copy the code (URL-decode if needed) and exchange within ~5 minutes:
firefinds ebay-oauth-exchange --code '<paste-code-here>'
firefinds ebay-user-token-status  # presence only
```

- [x] RuName created in Sandbox and pasted as `EBAY_RUNAME` / `EBAY_REDIRECT_URI`
- [x] `firefinds ebay-oauth-url` prints an `auth.sandbox.ebay.com` authorize URL
- [x] Sandbox seller user consents; `ebay-oauth-exchange` stores refresh token (mode 600)
- [x] `ebay-user-token-status` shows `refresh_token_present: true`
- [x] Token refresh path verified without printing secrets
- [x] Gates still OFF: `LIVE_LISTINGS_ENABLED` / `EBAY_SANDBOX_PUBLISH_ENABLED` /
      `EBAY_PRODUCTION_ENABLED` / `SUPPLIER_ORDERS_ENABLED` = false

**Exit criteria:** official Browse competition no longer needs
`provisional_public_ebay` / `needs_official_ebay_validation` for the pilot SKUs;
user refresh token present for upcoming sandbox Sell inventory/offer work
(still no publish until §2).

## 1c. Sandbox seller registration + Business Policies (Clay)

See [`SANDBOX_SELLER_REGISTRATION_STEPS.md`](SANDBOX_SELLER_REGISTRATION_STEPS.md).

- [ ] `TESTUSER_shopfirefindsnow`: `sellerRegistrationCompleted=true`
- [ ] Business Policies opted in on Sandbox; payment/return/fulfillment policies exist for `EBAY_CA`
- [ ] Real policy IDs stored (secure/env) — **never fabricate**
- [x] Final 5 `categoryId` resolved via Taxonomy (`16204` toners / `112529` headphones)

## 2. Sandbox / API validation

> **Gate split (2026-09-04):** Sandbox **inventory + offer** writes are allowed when
> `EBAY_ENV=sandbox` and a user refresh token is present — **without**
> `LIVE_LISTINGS_ENABLED`. Publish stays refused unless
> `EBAY_SANDBOX_PUBLISH_ENABLED=true`. Production Sell remains behind
> `EBAY_PRODUCTION_ENABLED` + `LIVE_LISTINGS_ENABLED`.
>
> **CLI:** `firefinds ebay-sandbox-inventory-offer-e2e` (Final 5 v2.1 drafts under
> `data/drafts/randmar_first/safe_nationwide/final5_v2_original/`). Optional overrides:
> `EBAY_FULFILLMENT_POLICY_ID`, `EBAY_PAYMENT_POLICY_ID`, `EBAY_RETURN_POLICY_ID`,
> `EBAY_CATEGORY_ID`. Reports: `data/reports/sandbox_inventory_offer_e2e_<ts>.{json,md}`.

- [x] Inventory API create/update inventory item against **sandbox** only — Final 5 v2.1 **5/5 OK** (`data/reports/sandbox_inventory_offer_e2e_20260904T195012Z.*`)
- [ ] Offer create/update against sandbox only — **0/5**; exact eBay error **25709** “Invalid value for categoryId.” (drafts still use `placeholder`). Next: set real `EBAY_CATEGORY_ID` / draft category; Business Policy eligibility (`sellerRegistrationCompleted:false`; prior fulfillment-policies 400) may block after category is fixed
- [ ] Policy IDs (fulfillment / payment / return) resolved for sandbox
- [x] MAP floor + stock buffer + shipping RESOLVED re-checked in backend gates (dry-runs 5/5)
- [x] Publish refused while `EBAY_SANDBOX_PUBLISH_ENABLED=false` (E2E asserts `EbayPublishDisabled`)
- [ ] Flip `EBAY_SANDBOX_PUBLISH_ENABLED=true` **only** for a named sandbox SKU set
- [ ] Sandbox publish → verify listing shape → unpublish / clean up
- [ ] Re-set `EBAY_SANDBOX_PUBLISH_ENABLED=false` after validation
- [x] No supplier Process / orders during this stage

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
- [`STAGE2_WAVE_SIZING_PLAYBOOK.md`](STAGE2_WAVE_SIZING_PLAYBOOK.md) — Final 5 → 10 → 25 (blocked until RuName → sandbox §2 → Clay)
- Fee readiness: `data/reports/ebay_ca_fee_model_149_book.md` · Store trigger: `data/reports/stage2_store_trigger_memo.md`
- Pack v2.1: [`SANDBOX_PILOT_PACK_v2.md`](SANDBOX_PILOT_PACK_v2.md) · dry-runs `data/reports/sandbox_pack_v2_dry_runs.md`
- First-wave 25 dry-runs (**25/25 PASS**): `data/reports/first_wave_25_dry_runs_20260904_1311.md`
- Cohort pointer: `data/reports/cohort_refresh_latest.md` (`20260904_1348`)
- CLI: `ebay-oauth-url`, `ebay-oauth-exchange`, `ebay-user-token-status`,
  `ebay-sandbox-inventory-offer-e2e`, `split-cohorts`, `authorize-drafts`,
  `batch-creative-drafts`, `ebay-demand-ingest`, `dry-run-sku`, `health`

# Sandbox seller registration + Business Policies (TESTUSER_shopfirefindsnow)

**Purpose:** Unblock Sandbox **Offer** create for Final 5 after Inventory E2E (Inventory **5/5** already OK).  
**Do not:** publish offers, flip `EBAY_SANDBOX_PUBLISH_ENABLED`, place supplier orders, or invent policy IDs.

## Current API state (2026-09-04)

| Check | Result |
|-------|--------|
| User OAuth refresh token | present (`secrets/ebay_user_refresh_token.txt`, mode 600) |
| `GET /sell/account/v1/privilege` | `sellerRegistrationCompleted: **false**` |
| `GET /sell/account/v1/fulfillment_policy?marketplace_id=EBAY_CA` | **400** — *User is not eligible for Business Policy* |
| Inventory create/replace Final 5 | **5/5 OK** |
| Offer create Final 5 | blocked (was categoryId placeholder; now fixed — still needs real policy IDs) |

## Minimal Clay steps

Sign in everywhere as Sandbox seller **`TESTUSER_shopfirefindsnow`** (password from [Developer Portal → Test users](https://developer.ebay.com/my/keys) / User Access Tokens area). Use **sandbox** hosts only (`sandbox.ebay.com`), never production.

### A. Complete seller registration (`sellerRegistrationCompleted → true`)

1. Open [https://www.sandbox.ebay.com/](https://www.sandbox.ebay.com/) and sign in as `TESTUSER_shopfirefindsnow`.
2. Start / finish the **Sell** registration flow (Seller Hub “Start selling” / account registration prompts until the account is a registered seller on Sandbox).  
   - Official meaning of the flag: Account API `getPrivileges` → `sellerRegistrationCompleted` is true only when eBay considers seller registration complete ([SellingPrivileges](https://developer.ebay.com/api-docs/sell/account/types/api:SellingPrivileges)).
3. Ping Mr. Krabs (or re-run privilege check) — we verify with:
   ```bash
   # presence-only privilege probe (no secrets printed)
   PYTHONPATH=backend:. python -m firefinds.cli.main ebay-user-token-status
   # plus a privilege GET — expect sellerRegistrationCompleted: true
   ```

### B. Opt into Business Policies (eligibility)

4. While signed in as the same Sandbox seller, open the Sandbox Business Policies opt-in page:  
   **[https://www.bizpolicy.sandbox.ebay.com/businesspolicy/policyoptin](https://www.bizpolicy.sandbox.ebay.com/businesspolicy/policyoptin)**  
   (Alternate host seen in guides: `http://www.bizpolicy.sandbox.ebay.com/businesspolicy/policyoptin`.)
5. Click **Try Out** / **Get Started** / **Opt in** (wording varies) and accept until Business Policies is enabled for the account.  
   - Until this succeeds, Account API policy GETs return *User is not eligible for Business Policy*.

### C. Create the three policies (EBAY_CA) and copy real IDs

6. In Sandbox Seller Hub / Business Policies dashboard (or [eBay API Explorer](https://developer.ebay.com/my/api_test_tool) against **Sandbox** with the user token), create **one each** for marketplace **EBAY_CA**:
   - Payment policy
   - Return policy
   - Fulfillment (shipping) policy
7. Copy the three numeric/string **policy IDs** (from the UI or from):
   - `GET /sell/account/v1/payment_policy?marketplace_id=EBAY_CA`
   - `GET /sell/account/v1/return_policy?marketplace_id=EBAY_CA`
   - `GET /sell/account/v1/fulfillment_policy?marketplace_id=EBAY_CA`
8. Send the three IDs to Mr. Krabs via **secure fields** (preferred), or confirm they may be stored as env:
   - `EBAY_SANDBOX_PAYMENT_POLICY_ID`
   - `EBAY_SANDBOX_RETURN_POLICY_ID`
   - `EBAY_SANDBOX_FULFILLMENT_POLICY_ID`  
   **Never invent IDs.** Placeholders stay until these exist.

### D. After IDs land (CTO does this — not Clay)

9. CTO replaces draft `listingPolicies` placeholders + retries **Offer** create only; **publish stays hard-refused** (`EBAY_SANDBOX_PUBLISH_ENABLED=false`).
10. Optional later (needed for *publish*, not for this Offer retry): create an inventory location via `createInventoryLocation` — noted by Sandbox listing guides; we will not publish in this phase.

## Verification checklist

- [ ] `sellerRegistrationCompleted: true`
- [ ] Policy list endpoints return ≥1 policy each (no “not eligible” error)
- [ ] Three real policy IDs stored (secure / env)
- [ ] Final 5 `categoryId` already resolved (toners `16204`, headphones `112529`) — see `data/reports/final5_category_resolution_*.md`
- [ ] Offer E2E re-run; publish still refused
- [ ] Gates remain OFF: `LIVE_LISTINGS` / `EBAY_SANDBOX_PUBLISH` / `EBAY_PRODUCTION` / `SUPPLIER_ORDERS`

## Sources

- Account API privileges / `sellerRegistrationCompleted` field definition  
- Sandbox listing prerequisites (policies + inventory + offer): community guidance summarizing Inventory API flow  
- Business Policies Sandbox opt-in URL: `bizpolicy.sandbox.ebay.com/businesspolicy/policyoptin`


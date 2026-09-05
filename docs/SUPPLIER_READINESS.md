# Supplier readiness — 2026-09-05

Status: **not yet approved for unattended purchases or new publication**.
No real supplier order or eBay write was performed during these checks.

## Verified against the live supplier

- Read current Product responses for all 48 verified existing SKU mappings.
  46 are buyable, non-opportunity-only CAD products with interpretable stock,
  price and MAP. This is product eligibility, NOT full listing qualification.
- SKU `6100176`: `AvailableToBuy=false`. SKU `HPW2020XC`:
  `AvailableToBuy=false`, `OpportunityOnly=true`. Both must remain outside
  automatic purchasing and new-publication eligibility. Existing eBay offers
  were not changed; their availability needs operational attention.
- Account permits system integration, is not on hold, and uses STRIPE /
  Starter-tier credit-card payment terms. The account's `IsQualified=false`
  does not mean all products are unavailable: 46 Product responses explicitly
  say buyable. The displayed credit limit is not proof of usable payment terms.
- User-authorized public reseller profile saved and independently checked via
  Account GET: Fire Finds, business email/website, and supplied business phone.
  The user's personal name was not used for this public contact profile.
- Reviewed Randmar's linked June 2026 Brand Directory, relevant printing,
  Elevate, HP and Xerox pages. Its "Open to all" / "Restricted" labels are
  explicitly under **Amazon Strategy**, not eBay permission. HP's page notes
  qualification requirements for most categories and a special contract-toner
  program. No eBay text was found in the directory; this does not establish a
  prohibition, but it also cannot satisfy the requested channel-permission gate.
  Source: public PDF linked by the signed-in Explore Manufacturers screen,
  `data/contracts/Randmar Brand Directory.pdf` (unmodified, excluded from Git).
- Created one explicitly owned `ff-quote-*` cart for Elevate SKU
  `2T4G0ZZSH1P2BUOU8KMU`, quantity one, and obtained four shipping services for
  each of five public screening destinations. Lowest observed charges were
  Calgary C$10.00, Vancouver C$12.50, Toronto C$10.00, Montreal C$12.51, Halifax
  C$16.69. Deleted that quote cart successfully; never called ProcessNew.
  These are sample-address screening quotes, not nationwide shipping coverage,
  tax-inclusive checkout totals, or delivery guarantees.

Private observations live under `data/supplier-readiness/` (ignored by Git).
Product audit observations were collected approximately 20:41–20:42 UTC;
they expire for live decisions and must be refreshed before purchases/listing.

## Implemented from observed contracts

- Read-only Product, Manufacturer and Account methods.
- Quote-only client permits changes solely to explicitly owned quote carts;
  supplier purchasing is structurally refused, independent of configuration.
- Strict Product normalizer binds SKU, CAD cost/MAP and nonduplicated active
  Canadian warehouse stock to positive purchasing permission.
- Worker now requires that fresh full Product evidence. The actual cart
  projection omits purchasing flags; absence there is no longer mistaken for
  a denial, nor treated as independent permission. Explicit contradictory cart
  flags still hold the order. Cost/MAP/stock mismatches also hold it.
- Strict quote parser refuses missing/invalid charges, uses the higher of Fees
  and RealShippingCharges, does not assume a promotional discount applies, and
  does not interpret the undocumented Date field as a promised delivery date.
- Reproducible read-only SKU audit and non-purchasing quote probe scripts.
- Full test suite: **404 passed**. Purchase/tracking lifecycle tests still use
  fake adapters; this count does not certify real end-to-end fulfillment.

## Remaining launch requirements

- [ ] Confirm supported unattended payment/settlement for this STRIPE account.
      ProcessNew returning an order number alone is not proof of paid release.
- [ ] Resolve eBay channel permission, content/image usage and return-risk
      evidence per manufacturer/product; purchasing permission is insufficient.
- [ ] Finish live buyer-specific checkout evidence collection, tax/fee/refund
      normalization and verified delivery-service promises.
- [ ] Verify real supplier PO-not-found and positive reconciliation contracts;
      never retry an uncertain purchase merely because a lookup is empty.
- [ ] Complete Sandbox/dry-run end-to-end acceptance with real response shapes.
- [ ] Finish attributable eBay demand/competitive-price collection and catalogue
      ranking; supplier sales or asking prices are not verified eBay sell-through.
- [ ] Deploy deterministic services, shared purchase/publication reservations,
      alerts and recovery checks on an always-on runner, independent of AI.
- [ ] Re-read actual remaining eBay allowance immediately before allocation;
      apply both unit/value limits, 18%/C$8 floors, MAP and stock buffers.

Runbook: `python3 scripts/audit_supplier_buyability.py --mapping
data/fulfillment-readiness/verified_sku_mapping.json --secrets-dir secrets
--reseller-id <reseller-id> --out data/supplier-readiness/listed-buyability.json`.
Quote probe: `python3 scripts/supplier_quote_probe.py --sku <sku> --secrets-dir
secrets --reseller-id <reseller-id> --out data/supplier-readiness/<probe>`.

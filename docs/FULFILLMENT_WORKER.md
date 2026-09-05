# Fulfillment implementation checkpoint — 2026-09-05

Status: **tested connected worker, not live automatic fulfillment**. Existing
listings still need manual handling when an order arrives. No Grok execution,
supplier purchase, listing mutation, or tracking POST was used for this check.

## Independently observed

- Randmar's supported V4 catalog report returned 19,583 products.
- All 48 existing eBay listings have exact supplier-product mappings, using
  merchant SKU plus checked GTIN or MPN/manufacturer identity. The comparison
  used the actual eBay inventory records and published offers, not titles alone.
- No listed quantity exceeded available stock minus the configured buffer of
  two, and no listed price was below the catalog MAP in this snapshot. This
  does not prove profitable delivery to every buyer or channel authorization.
- One item, `HPW2020XC`, is `OpportunityOnly=true`. Default-path purchasing is
  held. Its listing was not changed. HP describes W2020XC as a contractual toner
  in its [official supplies brochure](https://h20195.www2.hp.com/v2/GetPDF.aspx/4aa5-4602enw.pdf).
- The HP Canada/HP identity difference is narrowly resolved only for supplier
  manufacturer ID `25150` when BOTH MPN and checksum-valid GTIN agree. HP's
  [Canadian SU858A product page](https://www.hp.com/ca-en/shop/products/supplies/hp-mlt-d118l-high-yield-black-original-toner-cartridge-su858a)
  also supports that branding. This alias grants no resale permission.
- A new production order sweep returned zero orders in the API's default
  lookback window. This was a one-time check, not a deployed monitor.
- A read of a unique nonexistent Randmar PO returned `None`. A single negative
  probe is not sufficient to certify all not-found/error semantics; the live
  adapter is NOT marked as having a verified PO-absence contract.

Private, ignored evidence is under `data/fulfillment-readiness/`. The inventory
comparison preserves the original observation time when re-evaluated offline;
an offline check cannot make stale stock fresh.

## Connected workflow

`FulfillmentWorker.run_order` now coordinates these steps:

1. Refresh the eBay order and require paid, uncancelled, new, exact single-line
   inventory with a usable buyer address and explicit supplier mapping.
2. Require buyer-bound checkout evidence: current catalog/quote observations,
   channel/returns/MAP records, eligible shipping service, CAD net revenue and
   complete landed costs plus an upper bound on platform fees. Missing evidence
   holds. Catalog and quote observations must both be at most five minutes old.
3. Check exact cart identity, one SKU, quantity, current cost and buyability;
   reject opportunity-only inventory. Apply stock buffers, MAP, target margin
   and minimum contribution profit using complete order costs.
4. Reconcile the supplier PO, re-read eBay immediately before purchase, and
   re-read the cart. Changed payment/address/discount/cart evidence holds.
5. Reserve supplier cash against the C$2,500 Edmonton-day ceiling, and persist
   purchase facts and submission intent before one supplier attempt.
   A timeout/crash never causes a second automatic purchase. Recovery requires
   exact PO/order and SKU/quantity evidence; empty lookup never releases retry.
6. Match the full shipment to the purchased line and explicit carrier mapping.
   Persist a separate tracking intent, post at most once, and require eBay GET
   confirmation. Conflicting manual tracking, partial shipments and uncertain
   outcomes hold for reconciliation.

Audit records exclude buyer addresses/phones and API secrets. Checkpoints and
audit files are private and durable. All worker processes must use the same
POSIX state directory; independent/multi-host stores are unsupported. No system
can make the supplier write and local disk commit atomic; uncertain outcomes
are deliberately held instead of promising impossible exactly-once delivery.

The connected lifecycle and failure recovery are tested with in-memory supplier
and eBay adapters. No production evidence provider or live-write CLI is wired.
The API clients still independently enforce write gates. Listing writes now
also respect dry-run and the global kill switch, including Sandbox inventory.

## Read-only operational check

Run from the repository with matched mode-600 credentials in the secret store:

```sh
python3 scripts/fulfillment_check.py --environment production \
  --secrets-dir secrets --reseller-id 2WQN9V11G \
  --mapping data/fulfillment-readiness/verified_sku_mapping.json \
  --out data/fulfillment-readiness/production-orders
```

This command never loads `.env`, exposes an enable-write flag, requests buyer
checkout writes or starts a schedule. It pages through orders and feeds them
to the worker. New paid orders are reported as held pending verified checkout
evidence. Exit 2 means an incomplete sweep or an order needing attention.

## Launch checklist

- [x] Independent account credentials, catalog read, 48 identity checks.
- [x] Connected single-line worker, durable purchase/tracking recovery tests.
- [x] Read-only real-account sweep; no implicit mutation path.
- [ ] Production evidence provider: destination shipping/service compliance,
  authoritative fee/tax/discount normalization, current stock and cart quotes.
- [ ] Documented channel/returns evidence, particularly contractual toner.
- [ ] Verified supplier positive/negative PO contract and carrier mapping.
- [ ] Real permitted Sandbox paid-order/tracking E2E; seller readiness resolved.
- [ ] Controlled supplier test only within explicitly authorized payment scope.
- [ ] Multi-line orders and partial shipments (currently held safely).
- [ ] Always-on deployment, durable backups, alert destination, restart drills.
- [ ] Remaining-capacity collection/reservations and discovery/repricing loops.
- [x] Conditional activation authority received under `OPERATING_POLICY.md`;
  the actual readiness evaluation and activation remain incomplete.

Until these are complete, a published listing does not imply auto fulfillment.

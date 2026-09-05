# Randmar deterministic order path

All paths use `/V4/Reseller/{RANDMAR_RESELLER_ID}`. Supplier submission remains
off until the dry-run lifecycle and a separately approved controlled live test pass.

1. `GET /Order/PONumber/{ebayOrderId}`. Stop if an order already exists.
2. `POST /Cart/AddItem/{cartName}/{sku}/DefaultOpportunity?quantity=N`.
3. `GET /Cart/{cartName}` and revalidate SKU/quantity.
4. `POST /Cart/ShippingMethods/{cartName}` with `ShipToDetails`; select a returned
   `MethodId` only after shipping and margin gates pass.
5. Prepare `ProcessCartInput`, setting `PO` to the immutable eBay order ID.
6. **Irreversible and gated:** `POST /Cart/ProcessNew/{cartName}`.
7. Read `GET /Order/{orderNumber}` and `GET /Orders/Shipments`; match shipment by
   PO or order number and send real tracking through eBay's Fulfillment API.

The safe probe implements steps 1–5 and has no code path that invokes step 6.

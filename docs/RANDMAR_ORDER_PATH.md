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

## Verified integration status

On 2026-09-05, the dedicated `Fire Finds Order Router` OAuth client was
authenticated against Randmar V4 and a no-purchase cart probe returned HTTP 200
from:

`POST /V4/Reseller/2WQN9V11G/Cart/AddItem/ff-ebay-FF-PROBE-DO-NOT-SUBMIT/CN0628C002/DefaultOpportunity?quantity=1`

The response body was `true`. The probe cart then returned HTTP 200 from
`POST /Cart/ShippingMethods/{cartName}` and supplied actual carrier method IDs,
verifying the shipping-quote request shape. No `ProcessNew` request was made, so
no supplier order or payment was created. Authentication, the supported
default-opportunity cart mutation, and shipping quote are now verified;
idempotent PO lookup, tracking retrieval, and eBay Sandbox fulfillment still
need E2E evidence.

# Randmar machine order path (from official OpenAPI)

Source: `GET https://api.randmar.io/swagger/V4/swagger.json` (title: Randmar.io API V4).
Auth: OAuth2 client-credentials `https://auth.randmar.io/connect/token`.
Base: `https://api.randmar.io`.
Reseller prefix: `/V4/Reseller/{resellerId}`.

Irreversible (do not call until a controlled live test is authorized):

- `POST /V4/Reseller/{id}/Cart/ProcessNew/{cartName}` body `ProcessCartInput` → `ProcessOrderNewResponse.OrderNumber`
- `POST /V4/Reseller/{id}/Cart/Process/{cartName}` legacy

Safe steps used by `randmar_order_probe` (no Process*):

1. `POST /Cart/AddItem/{cartName}/{sku}/DefaultOpportunity?quantity=`
2. `GET /Cart/{cartName}`
3. `POST /Cart/ShippingMethods/{cartName}` body `ShipToDetails` `{ShipTo: ShipToLocation}`
4. `GET /Order/PONumber/{resellerPONumber}` — if an order exists, stop (idempotent)
5. Build `ProcessCartInput` and log it. Do not POST it.

After a real order exists:

- `GET /Order/{orderNumber}`
- `GET /Orders/Shipments` — `TrackingNumber`, `ShipVia`, `OrderNumber`, `PONumber`

PO: put the eBay order id in `ProcessCartInput.PO`. Spec says look up that PO before ProcessNew so the same eBay order cannot create two Randmar orders.

`ProcessCartInput` fields (additionalProperties=false):
Name, Street1, Street2, City, ProvinceCode, PostalCode, CountryCode,
PO, CustomerPO, Comment, ShippingSlipComment, ContactName, ContactPhone,
ShippingMethodId, AllowPartialShipment, ShippingSlipFileB64, FutureOrderDate, OrderOnHold.

Official rules: no null strings; empty string for unused text; CountryCode CA|US; always set ContactName and ContactPhone; get ShippingMethodId from ShippingMethods first.

If ProcessNew returns 401/403 with current Integration key: ask Randmar for reseller API write / order-placement on this client id (catalog-read keys are not enough).

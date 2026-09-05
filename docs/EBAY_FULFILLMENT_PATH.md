# eBay paid-order and tracking path (official Sell Fulfillment API)

Marketplace: EBAY_CA.
Docs: https://developer.ebay.com/api-docs/sell/fulfillment/resources/methods

Read paid orders:

- `GET /sell/fulfillment/v1/order`
- `GET /sell/fulfillment/v1/order/{orderId}`

Filter paid / not shipped with `filter=orderfulfillmentstatus:{NOT_STARTED|IN_PROGRESS}`.

Push tracking after Randmar ships:

- `POST /sell/fulfillment/v1/order/{orderId}/shipping_fulfillment`

Body uses official createShippingFulfillment fields: lineItems, trackingNumber, shippingCarrierCode.

Do not call createShippingFulfillment until a real Randmar tracking number exists.
Need Sell user token with scope `https://api.ebay.com/oauth/api_scope/sell.fulfillment`.

# Fire Finds Order Router credentials

Reseller: `2WQN9V11G`.
Do not use the display name `Fire Finds catalog read` as `RANDMAR_CLIENT_ID`.
`RANDMAR_CLIENT_ID` must be the integration Client ID shown in the Randmar Dashboard.
`RANDMAR_CLIENT_SECRET` lives only in Grok/project secret storage. Never commit it.

## What Randmar documents

Official spec: `https://api.randmar.io/swagger/V4/swagger.json`
Auth text: "Get an API key from the Randmar Dashboard. Then use it to get a Bearer token from the token endpoint."
Token URL: `https://auth.randmar.io/connect/token`
Login: `https://auth.randmar.io/account`
OAuth scopes object in the spec is **empty**. Public docs do not show a self-serve "cart write" checkbox.

So: you can create a new Dashboard integration/key. We cannot prove from public docs that write is granted automatically. Create the key, then we probe. If AddItem / ShippingMethods / ProcessNew returns 401/403, send the support request below.

## What you do in the Dashboard (stop before pasting secrets here)

1. Open `https://auth.randmar.io/account` and sign in.
2. Open the reseller Dashboard / API or Integrations area.
3. Create a new integration named `Fire Finds Order Router`.
4. Copy the **Client ID** (the id string, not the pretty name).
5. Copy the **Client Secret** once. Put it only in Grok Bot secret store as `RANDMAR_CLIENT_SECRET`.
6. Put the Client ID in Grok Bot secret store as `RANDMAR_CLIENT_ID`.
7. Confirm `RANDMAR_RESELLER_ID=2WQN9V11G`.
8. Tell Grok "secrets installed — run the probe." Do not paste the secret in chat.

## Support request if write is blocked

To: Randmar API / reseller support
Account / reseller id: `2WQN9V11G`
Integration name: `Fire Finds Order Router`

Please enable machine-to-machine dropship fulfillment on this integration:
- POST `/V4/Reseller/2WQN9V11G/Cart/AddItem/{cart}/{sku}/DefaultOpportunity`
- GET `/V4/Reseller/2WQN9V11G/Cart/{cart}`
- POST `/V4/Reseller/2WQN9V11G/Cart/ShippingMethods/{cart}`
- POST `/V4/Reseller/2WQN9V11G/Cart/ProcessNew/{cart}` (`ProcessCartInput`)
- GET `/V4/Reseller/2WQN9V11G/Order/PONumber/{po}`
- GET `/V4/Reseller/2WQN9V11G/Order/{orderNumber}`
- GET `/V4/Reseller/2WQN9V11G/Orders/Shipments`

Use case: eBay.ca paid order → dropship to buyer address → return tracking. We will send eBay order id as `ProcessCartInput.PO` for idempotency.

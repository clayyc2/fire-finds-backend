# randmar_order_probe result (2026-09-04)

## Can the backend place a Randmar dropship order entirely by API?

**API contract: YES.**
Official spec `GET https://api.randmar.io/swagger/V4/swagger.json` exposes a deterministic write path. Browser/AI assistant is not required.

**Live proof on this Grok runner: NO.**
The project box secret path from `.env.example` is `/workspace/firefinds/secrets/randmar_api_key.txt`.
This Grok session is not that box. The path is not mounted. Env has no RANDMAR_* values. The probe was not allowed to invent a key or print one.

**Live proof still required on `/workspace/firefinds`:**
```
cd /workspace/firefinds
PYTHONPATH=backend python scripts/randmar_order_probe.py \
  --ebay-order-id FF-PROBE-DO-NOT-SUBMIT \
  --sku <in-stock-sku>
```
That process must stop before `POST /V4/Reseller/{id}/Cart/ProcessNew/{cartName}`.

## Exact endpoint sequence (Order Router)

All under `https://api.randmar.io/V4/Reseller/{resellerId}` with Bearer token from `https://auth.randmar.io/connect/token`.

| Step | Call | Irreversible |
|------|------|----------------|
| Stock/SKU | existing catalog ingest `POST /Report/Products/JSON` | no |
| Idempotency | `GET /Order/PONumber/{ebayOrderId}` | no |
| Cart add | `POST /Cart/AddItem/{cartName}/{sku}/DefaultOpportunity?quantity=` | no |
| Cart read | `GET /Cart/{cartName}` | no |
| Ship-to quote | `POST /Cart/ShippingMethods/{cartName}` body `{ShipTo: ShipToLocation}` | no |
| Place order | `POST /Cart/ProcessNew/{cartName}` body `ProcessCartInput` | YES |
| Status | `GET /Order/{orderNumber}` | no |
| Tracking | `GET /Orders/Shipments` (`TrackingNumber`, `ShipVia`) | no |

Legacy do-not-use-for-new-code: `POST /Cart/Process/{cartName}`.

PO field: `ProcessCartInput.PO` = eBay order id.
If PO lookup returns `OrderNumber`, do not ProcessNew again.

## If live probe gets 401/403 on AddItem / ShippingMethods / ProcessNew

Ask Randmar support to enable **reseller cart + order write** on Integration key `Fire Finds catalog read` (or issue a new write-capable key) for reseller `2WQN9V11G`.
Catalog-read-only is not enough to fulfill.

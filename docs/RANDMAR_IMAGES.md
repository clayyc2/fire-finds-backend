# Randmar supplier images (read-only)

Backfill authorized catalog **stills** for `SAFE_NATIONWIDE` SKUs. Public
endpoints need **no Integration secret**. Binaries live under `data/images/`
(gitignored); URLs + local paths are attached on `products` rows.

## Working endpoints (Public)

```
GET https://api.randmar.io/Product/{randmarSKU}/Images
GET https://api.randmar.io/Product/{randmarSKU}/Image/{imageId}
```

List returns `ProductImageInfo[]` (`ImageId`, `Url`, `IsPrimary`, `SortOrder`, …).
`Url` points at the same host’s `Image/{imageId}` still. Both work anonymously
(OpenAPI Public tag). Prefer these over manufacturer Images routes.

CLI (checkpointed, polite sleep, resume by default; downloads stills):

```bash
cd /workspace/firefinds/backend
PYTHONPATH=. python -m firefinds.cli.main backfill-images --snapshot-id 20260904_0140
```

Outputs:

| Path | Purpose |
|------|---------|
| `data/images/{sku}/*.png` (etc.) | Downloaded stills |
| `data/images/{sku}/metadata.json` | Image ids / urls / primary / local paths |
| `data/images/sku_image_urls.json` | SKU → URLs + metadata map |
| `data/images/backfill_progress.json` | Resume checkpoint |
| `data/images/backfill_summary.json` | Run summary |
| `products.image_urls` / `image_count` / `images_fetched_at` | SKU record columns |
| `products.supplier_image_urls` / `supplier_image_local_paths` | URL list + local paths JSON |

`LIVE_LISTINGS_ENABLED` and `SUPPLIER_ORDERS_ENABLED` must stay **OFF**. The
backfill refuses if either gate is on.

Do **not** use / rotate / touch `secrets/randmar_api_key.txt` for imagery.
Default CLI is public anonymous (`--use-token` only if explicitly needed).

## Manufacturer Images → 401 (expected with reseller auth)

```
GET /V4/Manufacturer/{routeManufacturerId}/Product/{randmarSKU}/Images
```

With the **Fire Finds catalog read** reseller Integration key this returns
**HTTP 401 Unauthorized** (probe confirmed). Causes / notes:

1. **Role mismatch, not a broken secret.** Manufacturer Product routes expect a
   manufacturer (or admin) application identity. A reseller catalog-read token
   is not authorized for that controller — OpenAPI marks 401/403 on this path.
2. **Do not rotate or overwrite** `Fire Finds catalog read` /
   `secrets/randmar_api_key.txt` to “fix” Images 401. That key remains the
   catalog + shipping quote credential.
3. **Optional future:** a **second** Integration key scoped for media (separate
   secrets file) only if the Randmar UI exposes a media-capable key —
   investigation / add-alongside only; never replace the catalog-read key.
4. Until then, **public `GET /Product/{sku}/Images` + `Image/{id}` is sufficient**.

## Never call (write / generate)

These create or mutate assets — **out of scope** for backfill:

- `PUT .../GenerateImage`
- `POST .../AppendImage`, `POST .../Image`, `POST .../Images` (upload)
- `POST .../Images/Reorder`, `DELETE .../Images/{imageId}`
- Partner `Generation/Image`, `Generation/ImageUrl`, `Product/.../Generate/Image`

## AI thumbs

AI-enhanced thumbs / creative B-arm image generation stays **deferred**. Draft
A/B may still use copy stubs; supplier stills from this backfill feed the
ORIGINAL_SUPPLIER imagery path only.

## Credentials policy

- Imagery backfill: **public endpoints**, no secret file access.
- Catalog / shipping: client id = Integration key **name** (`RANDMAR_CLIENT_ID` /
  `secrets/randmar_client_id.txt`); secret stays in `RANDMAR_CLIENT_SECRET_FILE`.
- Never print / log tokens or secret file contents.
- Do not scrape eBay for supplier imagery.

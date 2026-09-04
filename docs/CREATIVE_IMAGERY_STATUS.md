# Creative / imagery status (SpongeBob)

Updated: 2026-09-04T01:20:26+00:00

## Gates
- Publish / live listings: **OFF**
- Supplier orders: **OFF**
- AI thumbs: **deferred** until authorized original image exists (Randmar URL or local binary)
- Never scrape eBay listing images

## SAFE_NATIONWIDE image map
- Source: `data/images/sku_image_urls.json` (public `GET /Product/{sku}/Images`)
- Backfill summary: `data/images/backfill_summary.json` → **254/254 with ≥1 URL**, 0 missing
- Local binaries under `data/images/{sku}/`: **132/254** present; **122** SKUs missing downloaded files (URLs still available)
- Missing-binary sample (first 25): 2DRN3GM8HEHW0JH4JVL3, BFCZR5FVBZ0KJFM430YX, 2Y0QYRH2Z6VM00TR9175, 5DJ9NYPTKRNOO0FQBOZO, MOJNYEHTZD60D2Q4VNY9, 6200162, 6200164, J2XS94E0BX1HM2DHWXY4, N5JG80ZNDKHTY90CNP54, O9FE1RHC6PFZZZ5B72TC, 10343916609, O5GXH5VHEFJZZ71YR7MZ, ML00E02Z5NMBMWCBXSN3, GR575FFKBJLLLZ9YRXK5, F800SUDQCORPKKRRPNYN, 843730113905, XWC8GYZ1BVHT04QUQ1D2, O74DBL6G38TP5CRK9NXL, ND1RHK6423Y6F2SNUH6U, BRHGES2415PK, UVERZWL629MVP5S8ESUB, ZDQ8FGZJPLCWZ03V6VCK, BRHGE2415PK, 62ZXO0641FGZQ2FHR5F1, HEL5NU51SDEY3C0UU2US

## EBAY_DEMAND_FIRST
- **STANDBY** for Plankton pilot survivors funnel
- Will prepare ORIGINAL listing creative only for dropped SKUs (no invented SKUs)
- AI_ENHANCED optional twin only after a real source image

## Blockers
- None requiring CTO ping right now
- Incomplete local binary download is noted, not blocking URL-based ORIGINAL creative

Machine-readable copy: `data/notes/creative_imagery_status.json`

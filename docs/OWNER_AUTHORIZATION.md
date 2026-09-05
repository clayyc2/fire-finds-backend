# Owner authorization (2026-09-04)

Clay granted permission for the full fulfillment sequence.

Order of use (do not skip):

1. Practice probe — cart + shipping quote + PO lookup. No ProcessNew.
2. One controlled live Randmar buy after the probe returns a complete ProcessCartInput and no 401/403 on write-prep endpoints.
3. Auto-buy for real eBay paid orders only after that one live buy returns a Randmar order number and tracking can be read.

Do not flip SUPPLIER_ORDERS_ENABLED in committed files.
Do not list more items until step 3 is proven.

Blocked in this Grok session: Randmar client secret is not on this machine. Probe cannot call live API until the secret is available to the runner.

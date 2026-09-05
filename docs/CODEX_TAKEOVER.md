# Fire Finds takeover — 2026-09-05

Clay directed that Grok and Grok Bots stop all Fire Finds work. Their only
remaining permitted use is collecting existing handoff information. Codex owns
implementation; the eventual service must operate deterministically without an
AI chat session. Existing eBay listings were not ended or modified by this handoff.

## Shutdown evidence

Directly observed in the Grok Bot app: stop instructions were sent to Mr. Krabs,
Squidward and Sandy. Mr. Krabs relayed stop instructions to Plankton and SpongeBob;
both acknowledged. Three schedules still showed Active despite bots claiming
they were paused. Codex disabled those directly:

- Squidward: Live-48 T+2h Day-1 scorecard.
- Mr. Krabs: Event-watch 194850506413 morning check.
- Sandy: Launch priority scan.

The lead bot's four routines subsequently showed Paused. Plankton's event watch
showed Paused; SpongeBob had no routines. All bots stopped business execution;
Mr. Krabs was asked only for the encrypted existing-data export afterward.
Bot-reported filesystem gates are NOT yet independently verified: all commerce
writes false, both kill switches true. Local rebuild settings remain separately
test-only. No historical GO message authorizes resumed execution.

## Handoff claims requiring local verification

- Remote repository: `/workspace/firefinds`, main at
  `6d3c834777c296b0b46d9bb6969c945f7772cb66`, with uncommitted docs/scripts/assets.
- No long-running Fire Finds server; Grok host filesystem and bot routines only.
- 48 existing EBAY_CA qty1 listings; CLEAR4 publication had not started at stop.
- Supplier ordering and tracking automation were off; current orders still need
  independent checking and manual fulfillment until a worker is verified.
- Production policy IDs: payment `263705041024`, return `263705042024`,
  fulfillment `263705044024`; location `firefinds_laval_wh`.
- Sandbox OAuth/read checks reported successful; seller registration false and
  selling limit null. Claimed Sandbox 5/5 inventory/offer checks refused publish;
  this is not a complete paid-order/shipment lifecycle.
- Source records: `data/firefinds.db`,
  `data/ops/live_published_eligible_now_48.json`,
  `data/reports/codex_handoff_shutdown_latest.json`, and supporting reports/drafts.

These are handoff observations, not proof of current supplier stock, eBay limits,
listing eligibility or fulfilled orders. Unknown or stale evidence holds writes.

## Secure migration

The source is a separate remote host, not a locally mounted folder. Requested
authenticated Grok attachment export encrypted to a public certificate; private
decryption key remains only on Clay's Mac in ignored `secrets/` with mode 600.
Never put plaintext credentials, OAuth URLs/codes or private keys in chat or Git.

The export includes a consistent SQLite backup, code/docs/tests and outstanding
diff, credentials, settings, roster, reports and drafts. Large historical media
and snapshots are excluded initially and retained on the source. Preserve the
source until independently verified receipt; do not overwrite the rebuild.

`scripts/import_handoff.py` requires a checksum from the authenticated handoff,
decrypts privately, rejects unsafe/link/duplicate/oversized archive members and
extracts to a NEW review directory only. It does not source `.env`, install
credentials, execute incoming code or change commerce gates. Review all incoming
files as data. Import only explicitly selected environment-matched credential
files into private storage, keeping Sandbox and Production credentials separate.

## Remaining launch work

1. Verify encrypted export, compare incoming code, inspect DB/schema and mappings.
2. Install matched Sandbox credentials privately; independently repeat read checks.
3. Verify current production orders/listing roster read-only; hold unmapped orders.
4. Complete and test deterministic worker orchestration and failure recovery.
5. Deploy an always-on runner with protected secrets, durable shared state,
   scheduling, alerts and backups; no Grok dependency or bot schedules.
6. Prove permitted Sandbox/dry-run E2E, resolve compliance/account blockers,
   then obtain explicit scoped live activation approval. Live writes stay off.

## Verified local receipt and account reads

The seven encrypted parts were saved through authenticated Grok attachments.
The whole 27,036,769-byte CMS file matched SHA256
`fd2607a707298ee85967bae729feb45b3b8d4704c8749a3c7dff4a0795a2f7a5`.
Decryption and guarded extraction produced 2,974 private files under ignored
`data/handoff-20260905/review/firefinds/`. SQLite quick_check returned `ok`, with
19,525 product rows. Historical media/snapshots/assets remain on the source.
The source was told receipt is verified and to preserve originals/remain stopped.

Matched Sandbox and Production eBay credentials are installed as separately
suffixed mode-600 files in local `secrets/`. The imported `.env` was NOT activated.
`scripts/account_readiness.py` uses a GET-only Sell client with fixed safe settings
and no ambient credential overrides. Production-read testing exposed and fixed
an inherited bug: disabling production writes had incorrectly selected Sandbox
as the Sell host. Routing now follows the explicit environment, while writes
remain independently gated.

Independent local checks on 2026-09-05:

- Sandbox: all five read groups passed; seller registration false, cap unknown,
  zero orders returned. Report: `data/verification-20260905-sandbox/`.
- Production: all five read groups passed; seller registration true, selling
  limits 5,000 items and CAD 69,515.02; zero orders returned.
- Production roster: 48/48 exact listing-ID matches with PUBLISHED offers.
  Report: `data/verification-20260905-production-correct-host/`.

All commerce gates stayed false. A published offer does not prove current stock,
full shipping coverage, profitability, remaining monthly capacity, or automatic
fulfillment. The read reported no recent orders; it is not an all-time order audit.
Independent supplier freshness/identity reconciliation and the continuous worker
remain unfinished. No source code from the imported copy was intentionally run;
test discovery is now explicitly restricted to the rebuild's `tests/` directory,
excluding imported `data/` and `secrets/`.

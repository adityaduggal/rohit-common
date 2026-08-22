# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`rohit_common` is a custom Frappe/ERPNext app developed by Rohit Industries Group. **Requires Frappe & ERPNext v13** (branch `version-13`) — it is not a standalone project, it's installed as an app inside a Frappe bench and only runs in that context. Bench-root paths in this doc (e.g. `bench --site <sitename> ...`) are relative to wherever the bench lives on the machine you're running on — don't assume a fixed absolute path.

It acts as a central extension/validation/integration layer for ERPNext: Indian GST compliance (E-Invoicing and E-Way Bills via ASP/GSP APIs), custom document validations, transaction-level view security, and background housekeeping tasks. See README.md for the full directory/module breakdown — don't duplicate it here.

**Migration context**: `v14_migration_notes.md` documents that in Frappe/ERPNext v14, Indian GST/localisation features move to the standalone `india-compliance` app, and several other domains (HR, payments, chat, education, etc.) are decoupled into separate apps. Keep this in mind if asked about upgrade work — the `india_gst_api/` module here is the v13-era equivalent of what `india-compliance` will own post-upgrade. This app's ASP/GSP vendor is also mid-migration (Charteredinfo/TaxPro → WhiteBooks.in) — see the `india_gst_api/` architecture note below.

## Skills needed to work in this repo

- **Frappe framework fluency**: doc_events/hooks lifecycle, DocType metadata vs. controller code, `permission_query_conditions`/`has_permission`, background jobs via `frappe.enqueue`, patches vs. migrations.
- **ERPNext accounting/transaction domain**: GL Entry semantics, invoice/journal/payment entry submit-cancel lifecycle, period-close and freeze conventions — most validations and the transaction view-lock feature sit on top of this.
- **Indian GST compliance domain**: e-Invoicing (IRN/QR code via ASP/GSP), e-Way Bill lifecycle, GSTIN verification — needed for anything touching `india_gst_api/`.
- **MySQL/MariaDB**: several hot paths (reports, cleanup jobs, the transaction lock's `doctype_conditions` grammar) work directly in SQL, not just the ORM.
- See `.claude/skills/frappe-dev/SKILL.md` for this repo's house style (batched-query pattern for N+1s, query-count test guard, lint invocation).

## Commands

All commands run from the bench root, not from this app directory, using `bench`:

- Run this app's tests: `bench --site <sitename> run-tests --app rohit_common`
- Run a single test file: `bench --site <sitename> run-tests --module rohit_common.rohit_common.doctype.eway_bill.test_eway_bill`
- Apply migrations (schema + `before_migrate` patches): `bench --site <sitename> migrate`
- Open a bench Python console: `bench --site <sitename> console`
- Site-local Python environment: `<bench-root>/env/bin/python`

There is no separate lint/build/frontend toolchain in this app — JS assets in `public/js/` are plain Desk form scripts loaded via `doctype_js` in `hooks.py`, not bundled.

## Architecture

**Everything is wired through `hooks.py`.** This is the map of how the app plugs into Frappe/ERPNext — read it first when tracing behavior:
- `doc_events`: per-DocType `validate`/`autoname`/`on_submit`/etc. hooks, each pointing to a function in `rohit_common/validations/*.py`. This is where most business-rule enforcement lives (GSTIN checks, invoice tax-template matching, asset serial naming, etc.).
- `scheduler_events`: cron/hourly/daily/weekly/monthly jobs pointing into `rohit_common/scheduled_tasks/*.py` (GSTIN re-validation, e-invoice submission queue, token refresh, file/version cleanup).
- `override_whitelisted_methods` / `has_permission`: core Frappe behavior (file search, file permissions) is overridden in `core/file.py` rather than patched in Frappe core. The transaction view-lock feature (below) also wires `has_permission` + `permission_query_conditions`, for a different set of doctypes, via the same pattern.
- `before_migrate`: runs `before_migrate_patches.py`, used for one-off data-shape fixes needed before a schema migration (e.g. truncating `Sales Invoice.po_no` to fit a column width — see `v14_migration_notes.md` for why).

**Central configuration lives in DocTypes, not code.** The `Rohit Settings` single DocType (`rohit_common/doctype/rohit_settings/`) drives runtime behavior across the app: e-invoicing on/off + effective date, which DocTypes get background submit/cancel processing, auto-deletion age thresholds for attachments/versions, which DocTypes/roles may hold public attachments, and the transaction view-lock's locked doctypes + bypass role. When changing behavior, check whether it's actually a `Rohit Settings` field before hardcoding a constant.

**Transaction view-lock is a security/access-control feature**, not just a validation: `rohit_common/validations/transaction_lock.py`, wired via `has_permission`/`permission_query_conditions` in `hooks.py`, originally for 12 transactional doctypes (Sales/Purchase Invoice, POS Invoice, Journal Entry, Payment Entry, GL Entry, Delivery Note, Purchase Receipt, Stock Entry, Quotation, Sales/Purchase Order) and extended to `E-Invoice Submission Log` (2026-08-22, see `docs/designs/gst-asp-migration-whitebooks.md`) — check `LOCKED_DOCTYPE_DATE_FIELDS` in `transaction_lock.py` for the current, authoritative list rather than assuming it matches this doc. Once a document is older than its configured retention window (`Rohit Settings.locked_doctypes`, reusing the `Global Search DocType` child table), ordinary users can no longer view/list/print it — only a configured bypass role (and Administrator/System Manager, always exempt) can, and bypass reads are logged to `Transaction Lock Access Log`. This is read-restriction only; ERPNext's own `Accounts Settings.acc_frozen_upto` freeze still owns edit/cancel-locking, unchanged. See `docs/designs/transaction-view-lock.md` for the full design rationale, including two known/accepted gaps: General Ledger and Trial Balance (raw-SQL reports) don't respect the lock, and DocShare grants on a document must be actively revoked (daily scheduled task) since Frappe's permission engine ORs them over `has_permission`.

**GST/ASP integration (`india_gst_api/`) is a thin API client layer** — `einv.py` (e-invoicing/IRN), `eway_bill_api.py` (e-way bill lifecycle), `gst_api.py`/`gst_public_api.py` (GSTIN verification) all call out to government-authorized ASP/GSP endpoints and write results back onto Sales Invoice / eWay Bill documents. Credentials/tokens are stored on `Rohit Settings` (not `Rohit GST Settings`, despite the name — verified against `rohit_settings.json` and `common.py`'s `get_aspid_pass()`). **Vendor migration in progress**: moving off Charteredinfo/TaxPro to WhiteBooks.in as the ASP, with the new integration designed to line up with the shape `india-compliance` (the v14 successor app) expects, so the v14 upgrade doesn't require a second rewrite. The Public GST family (GSTIN search/return tracking, `gst_public_api.py`) is fully cut over as of 2026-08-22 — Charteredinfo's `gsp_session.py` is deleted. e-Invoice (`einv.py`) and e-Way Bill (`eway_bill_api.py`) are still on Charteredinfo/TaxPro live, with WhiteBooks equivalents built alongside pending sandbox verification. Check `TODOS.md` / recent design docs for current migration status before assuming either vendor's API shape.

**Async/background pattern**: heavy operations (invoices with ≥10 line items, e-invoice submission, address ERP sync) are queued rather than run inline, via `utils/background_doc_processing.py` and the `scheduled_tasks/` jobs, to avoid Desk request timeouts. Follow this pattern for any new operation that could be slow or hit an external API during a user-facing save/submit.

**Custom DocTypes** live under `rohit_common/rohit_common/doctype/`; validation *logic* for both custom and standard (core ERPNext) DocTypes is centralized in `rohit_common/rohit_common/validations/`, separate from the DocTypes it validates — don't look for validation code next to a standard DocType's own files, it isn't there.

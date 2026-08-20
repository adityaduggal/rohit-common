# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`rohit_common` is a custom Frappe/ERPNext app (v13, branch `version-13`) developed by Rohit Industries Group. It is not a standalone project — it's installed as an app inside a Frappe bench and only runs in that context. This repo (`/home/aditya/v12/apps/rohit_common`) is one app inside the bench at `/home/aditya/v12`.

It acts as a central extension/validation/integration layer for ERPNext: Indian GST compliance (E-Invoicing and E-Way Bills via NIC/GSP APIs), custom document validations, and background housekeeping tasks. See README.md for the full directory/module breakdown — don't duplicate it here.

**Migration context**: `v14_migration_notes.md` documents that in Frappe/ERPNext v14, Indian GST/localisation features move to the standalone `india-compliance` app, and several other domains (HR, payments, chat, education, etc.) are decoupled into separate apps. Keep this in mind if asked about upgrade work — the `india_gst_api/` module here is the v13-era equivalent of what `india-compliance` will own post-upgrade.

## Commands

All commands run from the bench root (`/home/aditya/v12`), not from this app directory, using `bench`:

- Run this app's tests: `bench --site <sitename> run-tests --app rohit_common`
- Run a single test file: `bench --site <sitename> run-tests --module rohit_common.rohit_common.doctype.eway_bill.test_eway_bill`
- Apply migrations (schema + `before_migrate` patches): `bench --site <sitename> migrate`
- Open a bench Python console: `bench --site <sitename> console`
- Site-local Python environment: `/home/aditya/v12/env/bin/python`

There is no separate lint/build/frontend toolchain in this app — JS assets in `public/js/` are plain Desk form scripts loaded via `doctype_js` in `hooks.py`, not bundled.

## Architecture

**Everything is wired through `hooks.py`.** This is the map of how the app plugs into Frappe/ERPNext — read it first when tracing behavior:
- `doc_events`: per-DocType `validate`/`autoname`/`on_submit`/etc. hooks, each pointing to a function in `rohit_common/validations/*.py`. This is where most business-rule enforcement lives (GSTIN checks, invoice tax-template matching, asset serial naming, etc.).
- `scheduler_events`: cron/hourly/daily/weekly/monthly jobs pointing into `rohit_common/scheduled_tasks/*.py` (GSTIN re-validation, e-invoice submission queue, token refresh, file/version cleanup).
- `override_whitelisted_methods` / `has_permission`: core Frappe behavior (file search, file permissions) is overridden in `core/file.py` rather than patched in Frappe core.
- `before_migrate`: runs `before_migrate_patches.py`, used for one-off data-shape fixes needed before a schema migration (e.g. truncating `Sales Invoice.po_no` to fit a column width — see `v14_migration_notes.md` for why).

**Central configuration lives in DocTypes, not code.** The `Rohit Settings` single DocType (`rohit_common/doctype/rohit_settings/`) drives runtime behavior across the app: e-invoicing on/off + effective date, which DocTypes get background submit/cancel processing, auto-deletion age thresholds for attachments/versions, and which DocTypes/roles may hold public attachments. When changing behavior, check whether it's actually a `Rohit Settings` field before hardcoding a constant.

**GST/NIC integration (`india_gst_api/`) is a thin API client layer** — `einv.py` (e-invoicing/IRN), `eway_bill_api.py` (e-way bill lifecycle), `gst_api.py`/`gst_public_api.py` (GSTIN verification) all call out to government ASP/GSP endpoints and write results back onto Sales Invoice / eWay Bill documents. Credentials/tokens are stored on `Rohit GST Settings`.

**Async/background pattern**: heavy operations (invoices with ≥10 line items, e-invoice submission, address ERP sync) are queued rather than run inline, via `utils/background_doc_processing.py` and the `scheduled_tasks/` jobs, to avoid Desk request timeouts. Follow this pattern for any new operation that could be slow or hit an external API during a user-facing save/submit.

**Custom DocTypes** live under `rohit_common/rohit_common/doctype/`; validation *logic* for both custom and standard (core ERPNext) DocTypes is centralized in `rohit_common/rohit_common/validations/`, separate from the DocTypes it validates — don't look for validation code next to a standard DocType's own files, it isn't there.

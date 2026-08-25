# Architecture: hooks.py and central configuration

**Everything is wired through `hooks.py`.** This is the map of how the app plugs into Frappe/ERPNext — read it first when tracing behavior:
- `doc_events`: per-DocType `validate`/`autoname`/`on_submit`/etc. hooks, each pointing to a function in `rohit_common/validations/*.py`. This is where most business-rule enforcement lives (GSTIN checks, invoice tax-template matching, asset serial naming, etc.).
- `scheduler_events`: cron/hourly/daily/weekly/monthly jobs pointing into `rohit_common/scheduled_tasks/*.py` (GSTIN re-validation, e-invoice submission queue, token refresh, file/version cleanup).
- `override_whitelisted_methods` / `has_permission`: core Frappe behavior (file search, file permissions) is overridden in `core/file.py` rather than patched in Frappe core. The transaction view-lock feature (see `architecture-transaction-lock.md`) also wires `has_permission` + `permission_query_conditions`, for a different set of doctypes, via the same pattern.
- `before_migrate`: runs `before_migrate_patches.py`, used for one-off data-shape fixes needed before a schema migration (e.g. truncating `Sales Invoice.po_no` to fit a column width — see `v14_migration_notes.md` for why).

**Central configuration lives in DocTypes, not code.** The `Rohit Settings` single DocType (`rohit_common/doctype/rohit_settings/`) drives runtime behavior across the app: e-invoicing on/off + effective date, which DocTypes get background submit/cancel processing, auto-deletion age thresholds for attachments/versions, which DocTypes/roles may hold public attachments, and the transaction view-lock's locked doctypes + bypass role. When changing behavior, check whether it's actually a `Rohit Settings` field before hardcoding a constant.

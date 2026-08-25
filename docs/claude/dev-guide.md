# Dev guide

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

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`rohit_common` is a custom Frappe/ERPNext app developed by Rohit Industries Group. **Requires Frappe & ERPNext v13** (branch `version-13`) — it is not a standalone project, it's installed as an app inside a Frappe bench and only runs in that context. Bench-root paths in this doc (e.g. `bench --site <sitename> ...`) are relative to wherever the bench lives on the machine you're running on — don't assume a fixed absolute path.

It acts as a central extension/validation/integration layer for ERPNext: Indian GST compliance (E-Invoicing and E-Way Bills via ASP/GSP APIs), custom document validations, transaction-level view security, and background housekeeping tasks. See README.md for the full directory/module breakdown — don't duplicate it here.

**Migration context**: `v14_migration_notes.md` documents that in Frappe/ERPNext v14, Indian GST/localisation features move to the standalone `india-compliance` app, and several other domains (HR, payments, chat, education, etc.) are decoupled into separate apps. Keep this in mind if asked about upgrade work — the `india_gst_api/` module here is the v13-era equivalent of what `india-compliance` will own post-upgrade. This app's ASP/GSP vendor is also mid-migration (Charteredinfo/TaxPro → WhiteBooks.in) — see `docs/claude/architecture-gst-integration.md`.

## Where to look

Detailed guidance lives in `docs/claude/`, split by topic to keep this file short — read the relevant one when the task touches that area:

- `docs/claude/dev-guide.md` — skills/domain knowledge needed, and all `bench` commands (tests, migrate, console).
- `docs/claude/architecture-hooks.md` — how `hooks.py` wires the app together (`doc_events`, `scheduler_events`, permission overrides, `before_migrate`), and the `Rohit Settings` DocType that drives runtime config.
- `docs/claude/architecture-transaction-lock.md` — the transaction view-lock feature (read-restriction on aged transactional docs), locked doctypes, bypass role, known gaps.
- `docs/claude/architecture-gst-integration.md` — the `india_gst_api/` GST/ASP client layer, the Charteredinfo→WhiteBooks.in vendor migration status, the async/background job pattern, and where custom DocTypes/validations live.

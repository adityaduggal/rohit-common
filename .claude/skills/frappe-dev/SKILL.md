---
name: frappe-dev
description: Dev workflow and house style for the rohit_common Frappe/ERPNext app - bench commands, the batched-query pattern for avoiding N+1s, the query-count test guard, and lint invocation.
---

# frappe-dev

Working notes for developing in this repo (`rohit_common`, a Frappe v13 app).
For architecture and module layout, read `/CLAUDE.md` at the repo root first -
this skill covers the day-to-day commands and code-style conventions that
CLAUDE.md doesn't.

## Commands (run from the bench root, not this app directory)

```bash
# Full app test suite
bench --site <sitename> run-tests --app rohit_common

# Single test module
bench --site <sitename> run-tests --module rohit_common.rohit_common.scheduled_tasks.test_delete_unneeded_files

# Apply migrations / before_migrate patches
bench --site <sitename> migrate

# Bench python console (site context loaded)
bench --site <sitename> console

# Lint (this app uses black + isort + flake8, matching this bench's actual
# v13 frappe/erpnext tooling - NOT ruff, which is a v14+ convention)
pre-commit run --all-files
```

## House style: avoid N+1 queries

This codebase had a pass (see git history around the N+1 elimination plan) to
remove per-row `frappe.db.sql()` / `frappe.get_doc()` / `frappe.db.get_value()`
calls inside loops. When writing new code that processes many rows, follow the
same pattern:

1. **If you only need to read a few fields from many records**, batch-fetch
   them before the loop with `frappe.get_all(doctype, filters=[["name", "in",
   names]], fields=[...])`, build a `dict` keyed by name, then do `.get(key)`
   lookups inside the loop.
2. **If a required key is missing from the batched dict** (e.g. because the
   referenced row was deleted or never existed), fail loud with
   `frappe.throw(...)` naming the missing key - don't silently skip. This
   matches how `frappe.get_doc()` would have raised on a missing reference,
   and avoids masking data integrity problems.
3. **If you genuinely need to mutate/save/submit/cancel a document** (not
   just read a field), `frappe.get_doc()` per row is legitimate - Frappe's
   hooks and validation require a real Document instance. Don't force a
   `get_all`-only pattern onto a doc-mutation loop; that's not what's slow,
   and skipping hooks for speed is a bigger, separate decision to have
   explicitly with whoever owns the codepath.
4. **Reuse data you've already fetched.** If a loop already selected the
   fields you need for a "parent lookup" (e.g. a self-referential tree),
   build a dict from that same result set instead of issuing a fresh query
   per row - see `check_correct_folders()` in
   `rohit_common/rohit_common/scheduled_tasks/delete_unneeded_files.py` for
   an example (parent folder's archive flag is looked up from the already-
   fetched folder list, zero extra queries).
5. **Parameterize raw SQL values**, never interpolate them into the query
   string with `%` or f-strings - use `frappe.db.sql(query, {"key": value})`.
   Table/column names (which can't be parameterized) may be interpolated only
   when they come from a fixed, hardcoded source, never from user input.

## Query-count regression guard

`rohit_common/utils/query_guard.py` provides `assert_max_queries`, a test
context manager that fails the test if more SQL statements run than expected:

```python
from rohit_common.utils.query_guard import assert_max_queries

def test_something_stays_batched(self):
    with assert_max_queries(10, test_case=self):
        my_batch_processing_function()
```

Wrap any new batch-processing function's test with this, using a ceiling
based on the number of *distinct tables/queries* the function should issue
(roughly constant), not the number of rows it processes. This is what catches
a future edit that accidentally reintroduces a per-row query.

## Tests in this app

This app predates `frappe.tests.utils.FrappeTestCase` (a v14+ addition) - all
tests here use plain `unittest.TestCase`. `bench run-tests` still sets up
site/DB context around each test method, so `frappe.db.*` and `frappe.get_doc`
work normally inside test methods. Use `frappe.db.rollback()` in `setUp`/
`tearDown` to isolate test data (see `test_delete_unneeded_files.py` and
`test_rohit_common_utils.py` for the pattern used here).

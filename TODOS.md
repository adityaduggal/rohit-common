# TODOS

Deferred work, tracked with enough context to pick up later. Not a backlog of
every idea - only things explicitly deferred during a review rather than done.

---

## CI workflow (GitHub Actions)

**What:** Add `.github/workflows/ci.yml` running `pre-commit run --all-files`
and `bench run-tests --app rohit_common` on every push/PR.

**Why:** The N+1-elimination pass (2026) added `.pre-commit-config.yaml`,
`.flake8`, and `pyproject.toml` (black/isort) to this repo, plus real test
coverage for the fixed hotspots. None of that runs automatically today -
violations and regressions are only caught if someone runs the commands
locally.

**Pros:** Catches lint violations and test regressions before merge instead
of after. Standard practice for any repo with a real pre-commit config.

**Cons:** Needs a bench-in-CI setup (a full site + MariaDB service container)
to run `bench run-tests`, which adds real workflow complexity - not a
copy-paste GitHub Action. Some upfront setup cost.

**Context:** This bench runs Frappe v13 (13.58.22), and this app's pre-commit
config deliberately matches that version's actual tooling (black + isort +
flake8, not ruff - see `.claude/skills/frappe-dev/SKILL.md` for why). Any CI
setup should pin the same Python/MariaDB versions as this bench to stay
representative.

**Effort:** S (human ~1-2 hrs / CC ~10 min)
**Priority:** P2
**Depends on:** Nothing - the pre-commit config and tests it would run already
exist as of this pass.

---

## india_gst_api/einv.py re-fetch chain

**What:** `einv.py`'s e-invoice generation chain (`gen_einv_json`,
`add_einv_doc_details`, `get_docno`, `get_eway_details`, and
`get_einv_item_details`) each independently call `frappe.get_doc()` for the
same Sales Invoice and its line items' GST HSN Codes, when invoked in
sequence from `auto_einvoice_tasks.make_einvoice_for_docs()`. For an invoice
with N items, this is roughly 3-5x redundant Sales Invoice fetches plus one
`frappe.get_doc("GST HSN Code", ...)` per item (only `description` and
`is_service` are actually used from that doc).

**Why deferred:** CLAUDE.md's `v14_migration_notes.md` documents that in
Frappe v14, GST/India-localisation features (including e-invoicing) move to
the standalone `india-compliance` app. That migration is currently paused
with the ASP/GSP vendor decision undecided (see project memory: "TaxPro GSP
migration - PAUSED"). Spending effort rewriting `einv.py`'s internals risks
being wasted work if this module gets replaced wholesale.

**Pros:** Real, measurable N+1 - this runs on every invoice, in production,
today, regardless of when v14 migration happens (which has no committed
date).

**Cons:** e-invoicing is a compliance-critical codepath (talks to the GSP/NIC
government API) - any refactor here needs careful testing against real
invoice data, more so than the other fixes in this pass, which stayed in
lower-risk internal batch jobs and validation hooks.

**Effort:** M (human ~2-3 hrs / CC ~20-30 min)
**Priority:** P2
**Depends on:** Revisit once the v14 / india-compliance migration decision
unpauses - if the module is being replaced soon, this becomes moot; if the
migration stays paused indefinitely, this should be picked up on its own.

---

## General Ledger report: opening balance shown for closed-FY zero-balance rows

**What:** The General Ledger report shows an opening Dr/Cr balance for
accounts even when the account's balance is zero going into a closed prior
FY - specifically expense accounts, which should never carry an opening
balance across a year-end close (they're P&L accounts, closed to zero every
FY). Party-wise rows have a related issue: they should show only the net
value, not separate opening Dr/Cr, once a party's FY is closed.

**Why deferred:** This needs custom report logic (a real change to how the
report computes/displays opening balances per account-type and per-party),
not a config tweak - explicitly held until version-16, where this app's
report layer gets deliberate custom coding rather than following ERPNext
core's General Ledger report shape as-is. Raised alongside the 2026-08
transaction-view-lock work (see `docs/designs/transaction-view-lock.md`),
where General Ledger/Trial Balance report changes were already found to be
risky to get right on the first pass (a role-restriction change there was
implemented and reverted during that same review - see that doc's "Report-
leak coverage" section for what went wrong).

**Pros:** Fixes a real correctness/readability issue - expense accounts
showing a nonzero-looking opening balance for a period that's actually
closed is confusing and can be misread as a data problem when it isn't one.

**Cons:** Report logic in this app has already burned effort once this cycle
(the reverted GL/Trial Balance role restriction) - rushing a second custom
change to the same reports without full design-and-review risks a repeat.
Waiting for v16's dedicated custom-report pass avoids that.

**Effort:** M (human ~1 day / CC ~1-2 hrs, once scoped)
**Priority:** P3
**Depends on:** version-16 custom report work. Do not attempt as a quick fix
on version-13/14/15 - explicitly held.

---

## e-Way Bill generation trigger rules

**What:** Scope what triggers e-Way Bill generation for a Sales Invoice -
value threshold, movement-of-goods conditions, and any exemptions - as its
own design pass, separate from the ASP/GSP migration.

**Why:** Raised during `/plan-eng-review` of the WhiteBooks.in ASP migration
(see `docs/designs/gst-asp-migration-whitebooks.md`). e-Way Bill code exists
in `eway_bill_api.py` but has never been used in production - the migration
covers the auth/plumbing swap to WhiteBooks for that module, but the actual
business rules for *when* to generate an e-way bill were never designed and
don't belong bundled into a vendor-migration doc.

**Pros:** Keeps the ASP migration design focused on its actual scope
(auth/plumbing, not new business logic). e-Way Bill still gets a proper
design pass - premise challenge, alternatives, edge cases - instead of
trigger rules getting improvised during implementation.

**Cons:** Adds one more office-hours/plan-eng-review cycle before e-way bill
can actually go live, on top of the migration itself.

**Effort:** S-M (human ~half day / CC ~30-45 min, once scoped)
**Priority:** P2
**Depends on:** The ASP migration's provider-swap half (Approach B layer)
landing first - e-way bill's auth still needs migrating to WhiteBooks
regardless of what triggers generation.

---

## GSTR1 Return RIGPL: build full unit test suite

**What:** Write unit tests for `gstr1_return_rigpl.py` - currently
`test_gstr1_return_rigpl.py` is an empty stub. Cover `validate_si_tables`,
`generate_hsn_summary`, `generate_synopsis`, `process_gstr1`/
`match_and_update_details_from_gstin` (mocking GSTN/WhiteBooks responses),
and the missing-table handling and tolerance-comparison fix landed in the
2026-08-26 `/plan-eng-review` pass.

**Why:** Raised during `/plan-eng-review` of `gstr1_return_rigpl/`. This is
the highest-stakes file in the doctype (GST compliance reconciliation, hard
`frappe.throw`s on any GSTN mismatch) with zero test coverage, and that
review's session landed several non-trivial fixes (12 new child tables,
SQL parameterization, an O(n^2) HSN-merge rewrite, N+1 batching, a
truncation-vs-tolerance fix in B2C reconciliation) with no regression
coverage proving they didn't break the reconciliation logic.

**Pros:** Proves the core reconciliation functions behave correctly;
catches regressions from the 2026-08-26 fixes; mirrors this repo's existing
`test_gsp_session.py`/`test_transaction_lock.py` pattern so there's a
template to follow.

**Cons:** Significant effort - needs mocked GSTN/WhiteBooks response
fixtures across many code paths (B2B/B2CL/CDN/export/B2C reconciliation
branches each have different response shapes).

**Effort:** L (human ~1-2 days / CC ~1-1.5 hrs)
**Priority:** P1
**Depends on:** Should land after the 2026-08-26 fixes are merged, so tests
are written against the corrected code (missing-table handling, dict-based
HSN merge, tolerance-based B2C comparison), not the code being replaced.

---

## GSTR1 Return RIGPL: finish or formally kill the submit workflow

**What:** `gstr1_return_rigpl.json` sets `is_submittable: 1`, but
`on_submit()` (gstr1_return_rigpl.py:167-170) runs `validate_export_invoices()`
and `validate_si_tables(submit=1)` - real validation work - then
unconditionally throws `"Submission is Not Allowed for the Time Being"`. No
document of this type can ever actually be submitted.

**Why:** Raised during `/plan-eng-review`. Either finish the submit
workflow (decide what "submitted" means for this doctype: does it lock the
record, trigger actual GST filing, just flip a status field?) or remove
`is_submittable`/`on_submit` entirely so the UI stops presenting a workflow
that can never complete.

**Pros:** Resolves confusing UX (a submit button that always fails after
doing real validation work first); forces an explicit product decision
instead of leaving a silent WIP block in place indefinitely.

**Cons:** Not just a code change - needs a product decision on GSTR1
submission semantics in this system first.

**Critical implementation note (found during outside-voice cross-model
review):** `validate_si_tables` (line 172-226) mutates child-row fields
(`receiver_address`, `receiver_gstin`, `receiver_name`) in memory but never
persists them - this is currently harmless only because the `on_submit`
throw always fires before anything downstream matters. Whoever unblocks
submission MUST also add `self.save()` or per-row `db_set()` calls for
these mutations, or submit will proceed with stale receiver data that was
never actually saved.

**Effort:** M (human ~2-4 hrs once submission semantics are decided / CC
~20-30 min)
**Priority:** P2
**Depends on:** A product decision on what GSTR1 submission should do.

---

## GSTR1 Return RIGPL: `check_dynamic_link` runs unconditionally on every JV-linked row

**What:** In `validate_si_tables` (gstr1_return_rigpl.py:196-204), for
Journal-Entry-linked rows, `receiver_address` is only *guessed* when empty
(`if not d.receiver_address: ...guess_correct_address(...)`), but
`check_dynamic_link` runs unconditionally on every such row regardless of
whether the address was just guessed or was already manually set. Investigate
whether this re-validates legitimate manually-set addresses on every
`validate()` call, and if a failure there produces a hard throw with no
visible explanation to the user of why their manually-set address was
rejected.

**Why:** Surfaced by the outside-voice cross-model review during
`/plan-eng-review` of this file. Not independently confirmed - moderate
confidence this is a real UX/correctness gap, not certain it's frequently
hit in practice, since `check_dynamic_link`'s actual failure modes weren't
traced during this review.

**Pros:** If confirmed, fixing it either scopes the check to guessed-only
addresses or improves the error message so users understand why a
manually-set address failed.

**Cons:** Needs investigation first (trace `check_dynamic_link`'s
implementation and failure modes) before deciding whether a code change is
even warranted.

**Effort:** S (human ~30-45 min investigation / CC ~10-15 min)
**Priority:** P3
**Depends on:** Nothing - can be picked up independently.

---

## GSTR1 Return RIGPL: local population for the 6 new amendment tables

**What:** `gstr1_return_rigpl.json` now has 6 new child-table fields
(`b2ba_invoices`, `b2cla_invoices`, `b2csa_invoices`, `cdb_b2ba`,
`cdn_b2ca`, `export_amend`) for B2B/B2CL/B2CS/CDN-Registered/
CDN-Unregistered/Export amendments - previously these had zero doctype
field, so `process_gstr1()` would hard-throw with "Data in GST Network but
Table for the Same is Empty" the moment GSTN returned any amendment data,
with no way to even manually reconcile. The fields reuse the `GSTR1 Return
Invoices` child doctype and slot into section breaks (`sb07`-`sb11`,
`sb20`) that were already scaffolded in the original 2021 doctype design
but never filled in.

Adding the fields makes manual entry/reconciliation possible for the first
time, but does **not** by itself stop the hard-throw: `get_invoices()` (the
method that auto-populates the 6 original tables from period-scoped Sales
Invoices) has no equivalent for amendments, and `clear_all_tables()` still
only lists the original 6 tables. Until a local-population query exists,
`self.get(tbl, [])` returns `[]` for these fields exactly as before the
fields were added, and `process_gstr1()` will still throw whenever GSTN
reports amendment data for a period where nothing was manually entered.

**Why deferred:** Detecting "which Sales Invoices were reported in an
earlier GSTR1 period and later amended/cancelled" is a genuinely new local
query - it depends on what "amendment" means operationally in this system
(ERPNext's own amend-after-submit flow? A manual correction workflow? A
credit/debit note against an already-filed invoice?), which needs a design
decision, not just code.

**Pros:** Once designed, closes the last gap in GSTR1 auto-reconciliation;
until then, at least unblocks manual entry so amendment periods aren't
categorically impossible to file from this doctype.

**Cons:** Needs a product/design decision on what counts as a
locally-amended invoice before any population code can be written safely -
same tax-compliance stakes as the rest of this doctype.

**Effort:** M (human ~1 day once scoped / CC ~30-45 min)
**Priority:** P2
**Depends on:** A design decision on local amendment detection. See also
the sibling TODO below for the 7 aggregate GSTR1 categories that still
have no doctype fields at all.

---

## GSTR1 Return RIGPL: 7 aggregate categories have no local data model at all

**What:** 7 of the 20 `gstr1_actions` entries still have no doctype field
and no local data model to reconcile against: `AT`/`ATA` (Advances Tax +
Amendments), `DOCISS` (Documents Issued), `EINV` (e-Invoices), `NIL` (Nil
Rated Supplies), and `TXP`/`TXPA` (Tax Paid + Amendments). Unlike the 6
amendment tables above (which reuse the existing `GSTR1 Return Invoices`
shape), these are not invoice-shaped at all:

- `AT`/`TXP`/their amendments track advance-receipt GST liability and its
  later adjustment - there is no advance-receipt GST tracking anywhere in
  `rohit_common` today (confirmed by grep during the 2026-08-26
  `/plan-eng-review`).
- `DOCISS` reports invoice-number-series ranges issued/cancelled per
  document type - no document-series tracking exists.
- `NIL` aggregates nil-rated/exempt supply totals - no such aggregation
  exists.
- `EINV` is an e-invoice/IRN summary - would need to cross-check against
  IRN data already written onto Sales Invoice by `einv.py`, but the shape
  GSTN expects here hasn't been checked against that.

**Why deferred:** Building these isn't a code fix, it's designing and
building 3-4 new subsystems (new doctypes, new local queries, and
reconciliation logic) from scratch, in a tax-compliance-critical doctype,
with no sample WhiteBooks/GSTN payload in this repo to verify field
mappings against (same "UNVERIFIED" caveat already flagged in
`get_gstr1_whitebooks()`'s docstring). Guessing at GSTN's public JSON
schema from memory and shipping it as reconciliation logic risks silent
wrong field mappings in a filing-adjacent doctype - worse than the current
explicit hard-throw.

**Pros:** Completes GSTR1 coverage for all 20 GST return categories -
today `process_gstr1()` will hard-throw the instant GSTN reports any data
in one of these 7 (which is only a matter of time for AT/TXP if the
business ever takes advances, or NIL if it ever has exempt supplies).

**Cons:** Largest, highest-risk item in this doctype's backlog - needs a
real design pass (`/plan-eng-review` or `/spec`) per category, ideally
against an actual sample WhiteBooks GSTR1 response, before any schema or
matching code is written.

**Effort:** L (human ~3-5 days once scoped, per category / CC ~1-2 hrs per
category once a design + sample payload exist)
**Priority:** P2
**Depends on:** A design pass per category, and ideally a real sample
GSTN/WhiteBooks payload to verify field mappings against - do not
implement from memory of the public schema alone.

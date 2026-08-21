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

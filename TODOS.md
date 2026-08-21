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

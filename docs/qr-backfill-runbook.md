# QR Code Backfill Runbook

Manual runbook for deciding whether to backfill `Sales Invoice.signed_qr_code`
from historical `qrcode_image` PNGs, and running the backfill once decided.
See `docs/designs/gst-asp-migration-whitebooks.md` (T7) for the full design
context — this doc is the operational checklist, not the design rationale.

**This step does not run itself.** The patch
(`rohit_common.patches.v13.backfill_signed_qr_code`) is registered in
`patches.txt` so it runs on every `bench migrate`, but it's gated behind
`frappe.flags.qr_backfill_confirmed` (defaults `False`) and does nothing —
just logs a warning — until you complete Step 1 below and explicitly confirm.
This is deliberate: no historical invoice data gets touched by an ordinary
migrate.

## When to run this

- Once, after `T6` (the `signed_qr_code` field) has synced to a site via
  `bench migrate`, for any site that has historical e-invoices with
  `qrcode_image` set.
- Not before — the field must exist first, and this decision is independent
  of the WhiteBooks ASP migration itself (T1–T5); it does not need the new
  ASP live to run.

## Step 1 — Run the sample check

```bash
bench --site <sitename> console
```

```python
from rohit_common.rohit_common.india_gst_api.qr_backfill import sample_decode_check
report = sample_decode_check(sample_size=50)
```

This prints a decode rate and returns a dict with per-invoice failure
reasons. **Needs `pyzbar` + the system-level `zbar` library installed**
(`pip install pyzbar` alone is not enough — `apt install libzbar0` on
Debian/Ubuntu, or the equivalent for your OS, is also required). If the
import fails with a `zbar shared library not found` style error, install
`zbar` first and retry — this hasn't been confirmed installable on any
specific bench as of 2026-08-22, per the design doc's own open item.

## Step 2 — Decide

- **Decode rate ≥ 95%**: proceed to Step 3.
- **Decode rate < 95%**: do not run the backfill. Historical invoices before
  `signed_qr_code` existed stay blank — a documented gap (Option (b) in the
  design doc), not a bug. Note the actual observed rate somewhere durable
  (this file, a TODOS.md entry, or a project memory) so a future session
  doesn't re-run Step 1 from scratch without knowing this was already tried.

## Step 3 — Run the backfill

Still from the same bench console session (or a fresh one):

```python
import frappe
frappe.flags.qr_backfill_confirmed = True
from rohit_common.rohit_common.india_gst_api.qr_backfill import backfill_signed_qr_code
report = backfill_signed_qr_code()
```

Or, non-interactively, via `bench execute` (note: `frappe.flags` is
per-process, so the flag has to be set inside the same execution — use the
console method above rather than trying to pass the flag externally).

This prints a summary (`N/total backfilled, M failed`) and returns the same
shape as the sample check. Per-invoice failures are logged to Error Log with
title `QR backfill: invoice not backfilled` — review those before considering
the backfill complete, per the design's "not silently skipped" requirement.

## Step 4 — Confirm

- Spot-check a handful of backfilled invoices: `signed_qr_code` should be a
  long, non-empty string, structurally distinct per invoice (not the same
  value repeated — that would indicate something went wrong upstream of the
  per-invoice decode).
- If the failure count is unexpectedly high compared to the Step 1 sample
  rate, stop and investigate before considering this done — a full-dataset
  run surfacing a much worse rate than the 50-sample check suggests the
  sample wasn't representative, not that the full run is fine to leave as-is.

## Rollback

There's no automatic rollback. If backfilled values turn out to be wrong
(e.g. `is_valid_signed_qr()`'s structural check passed but the decoded text
isn't actually a valid signed QR payload — see the design doc's caveat that
this validation isn't a real schema check), clear the field manually:

```sql
UPDATE `tabSales Invoice` SET signed_qr_code = NULL WHERE <criteria>;
```

Re-run the backfill after fixing whatever was wrong with the decode/validate
logic — `_candidate_invoices()` only selects invoices where `signed_qr_code`
is still empty, so a partial/corrected re-run is safe and won't re-touch
already-backfilled rows.

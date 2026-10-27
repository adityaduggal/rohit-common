# QR Code Backfill Runbook

This runbook covers how to fill `Sales Invoice.signed_qr_code` from the old
`qrcode_image` PNGs (issue #17). For the design, see
`docs/designs/gst-asp-migration-whitebooks.md` (T7).

The patch `rohit_common.patches.v13.backfill_signed_qr_code` runs
automatically on `bench migrate`. Its `patches.txt` line has the suffix
`#2026-10-27`. Frappe recorded the old `#2026-08-22` line as done, but that run
skipped its work because of a flag gate. A changed suffix makes Frappe run the
patch one more time. Keep one patch file: to run it again, change the suffix,
do not add a second file.

## What the patch does

1. It checks that the Python packages `zxing-cpp`, `Pillow`, `pyqrcode` and
   `pypng` are installed. If one is missing, the patch **fails migrate** and
   prints the install steps. Frappe does not record a failed patch, so the
   patch runs again on the next migrate.
2. If the `signed_qr_code` column does not exist yet, the patch syncs the
   app's custom fields. Patches run before migrate syncs custom fields.
3. For each Sales Invoice that has `qrcode_image` set and `signed_qr_code`
   empty, the patch:
   - reads the PNG from disk and decodes it with zxing-cpp;
   - checks that the decoded text re-renders to a **pixel-identical** PNG, with
     the same pyqrcode settings as `einv.attach_qrcode()`. This proves that the
     print formats will draw the same QR;
   - writes `signed_qr_code` with `db.set_value` (`modified` does not change).
4. Before it starts, it prints how many invoices it must backfill. During the
   run, one status line updates after each invoice:
   `QR backfill: 1200/26143 (4%) processed, 1150 backfilled, 50 failed`.
   It commits after each backfilled invoice, so if you stop the run, the next
   run continues with the invoices that are left.
5. Invoices that fail (for example, a file missing on disk) do **not** fail the
   patch. One Error Log entry, titled `QR backfill: invoices not backfilled`,
   lists them grouped by reason.

## Step 1: install the packages (each server, once)

These are pip-only packages. No `apt` package is necessary.

```bash
cd <bench-root>
bench setup requirements --python
# or only this app: ./env/bin/pip install -e apps/rohit_common
./env/bin/python -c "import zxingcpp, pyqrcode, png, PIL; print('ok')"
```

`zxing-cpp` is pinned to `2.2.0`, because that is the last version with a
Python 3.8 wheel. A newer version tries to build from source and fails.

## Step 2 (optional): run a sample check

```bash
bench --site <sitename> console
```

```python
from rohit_common.rohit_common.india_gst_api.qr_backfill import sample_decode_check
report = sample_decode_check(sample_size=50)
```

The sample check writes nothing. A failure with the reason `file missing on
disk` means that the PNG file is not on this server. Other reasons need a
closer look before you continue.

## Step 3: migrate

```bash
bench --site <sitename> migrate
```

## Step 4: examine the result

- Open the Error Log entry `QR backfill: invoices not backfilled`, if there is one.
- Spot-check some invoices. Open the print preview (Domestic Invoice or Export
  Invoice) and scan the QR with the GST e-invoice verify app.

## Run the backfill again

The backfill selects only invoices with an empty `signed_qr_code`. Thus you can
run it again at any time, for example after you restore the missing PNG files:

```python
from rohit_common.rohit_common.india_gst_api.qr_backfill import backfill_signed_qr_code
report = backfill_signed_qr_code()
```

## Known gap on dev-rb-v12 (2026-10-27)

The PNG files on dev are a partial copy:

| Year | PNG on disk | PNG missing |
|------|-------------|-------------|
| 2022 | 4,080 | 254 |
| 2023 | 5,512 | 336 |
| 2024 | 3,380 | 3,126 |
| 2025–2026 | 0 | 9,455 |

On dev, about 13k invoices fail with `file missing on disk`. This is
expected. Copy the files from production (`sites/<site>/private/files/QRCode_*.png`)
and run the backfill again. On a sample of 2,000 PNGs that are on disk, all
decoded and all matched pixel for pixel.

## Print formats

`Domestic Invoice` and `Export Invoice` draw the QR from `signed_qr_code`
through the Jinja method `get_einvoice_qr_data_uri` (`hooks.py` `jenv`,
`india_gst_api/qr_render.py`). They use `qrcode_image` only if
`signed_qr_code` is empty. Do not delete the PNGs until every invoice that
has a QR also has `signed_qr_code`.

## Rollback

There is no automatic rollback. To clear the backfilled values:

```sql
UPDATE `tabSales Invoice` SET signed_qr_code = NULL WHERE <criteria>;
```

The print formats then use the PNG again.

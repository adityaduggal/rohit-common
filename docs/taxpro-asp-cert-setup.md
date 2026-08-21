# TaxPro GSP ASP Certificate Setup

Runbook for generating/regenerating the RSA keypair used to authenticate to
TaxPro GSP's Public API (Search Taxpayer / Track Return only — this does
**not** affect e-Invoice or e-Way Bill, which use separate credentials and
are unaffected by any of this).

Background: effective 2025-03-01, TaxPro requires certificate-based session
auth (`GetKey`) for the Public API instead of the old `aspid`+`password`
query string. See issue #5 for the full context.

## When to run this

- First-time setup (the current situation as of issue #5 — the public cert
  is registered on TaxPro's GSP CRM but the matching private key is not
  present on the server and is presumed lost).
- The private key is ever compromised, lost, or needs rotating.

## Topology

Both consuming Frappe sites run on **one physical server, different
databases**. A single keypair and a single private key file (at one
filesystem path) serves both sites — you do not need a separate keypair per
site. TaxPro's own docs for `session-id` state "ASP may create multiple
Sessions," so both sites independently calling `GetKey` against the same
`aspid`/certificate is supported, not something to work around.

## Step 1 — Generate the keypair

```bash
openssl req -x509 -newkey rsa:2048 -keyout asp_private_key.pem -out AspDsc.cer \
  -days 3650 -nodes -subj "/CN=Rohit Industries Group ASP/O=Rohit Industries Group Private Limited"
```

- `asp_private_key.pem` — the private key. Never commit this to git, never
  paste it in chat/logs/tickets.
- `AspDsc.cer` — the public certificate, uploaded to TaxPro in Step 2.
- 2048-bit RSA is the minimum for RSA-SHA256 signing per TaxPro's GetKey docs.
- `-days 3650` (10 years) is a reasonable validity window; shorten if your
  org has a cert-rotation policy.

## Step 2 — Register the public cert with TaxPro's GSP CRM

1. Log in to `https://crm.gstefiling.co.in/APIUser/UpdateProfile`.
2. Under "AspDsc.cer File", click Browse and select the `AspDsc.cer` from
   Step 1.
3. Click Submit. Confirm the page shows "AspDsc.cer (AspDscPublicKey) File is
   Uploaded" in green — this replaces whichever cert was previously
   registered.

## Step 3 — Deploy the private key to the server

```bash
sudo mkdir -p /etc/rohit-gst
sudo mv asp_private_key.pem /etc/rohit-gst/asp_private_key.pem
sudo chown frappe:frappe /etc/rohit-gst/asp_private_key.pem   # bench-running user
sudo chmod 600 /etc/rohit-gst/asp_private_key.pem
```

Set `Rohit Settings > TaxPro GSP Public API Auth > ASP Private Key Path` to
`/etc/rohit-gst/asp_private_key.pem` on **both** sites (same path works for
both since they're on the same server).

Confirm the path is outside the git repo and matches nothing tracked —
`git status` in the app directory should show nothing related after this.

## Step 4 — Verify GetKey succeeds (before relying on it in application code)

Run this from a bench console (`bench --site <sitename> console`) on **each**
site independently:

```python
from rohit_common.rohit_common.india_gst_api import gsp_session
session = gsp_session.get_session(force_refresh=True)
print(session["session_id"], session["validity_min"])
```

A successful call prints a real `session_id` and `validity_min`. If it
raises "TaxPro GetKey failed: ...", the error message from TaxPro's response
is included — common causes: cert not yet propagated on TaxPro's side (wait
a few minutes after Step 2), `Rohit Settings.tax_pro_asp_id` mismatched, or
`sandbox_mode` pointing at the wrong environment.

**Do this against TaxPro's sandbox first** (`Rohit Settings > Sandbox Mode`
checked) before testing against production.

## Step 5 — Confirm both sites work independently

Run Step 4 on both sites in quick succession (within a minute or two of each
other) and confirm both return valid, distinct `session_id` values without
either failing. Note the actual observed behavior here if it differs from
"both succeed cleanly" — TaxPro's docs state multiple sessions are
supported, but this hasn't been verified against this specific account.

## Security notes

- The private key file must never be committed to git — confirmed via
  `.gitignore`/path convention above (`/etc/rohit-gst/`, outside the repo
  entirely).
- `chmod 600` + correct owner is the minimum bar; consider your org's
  broader secrets-management approach for anything more sensitive.
- Rotating the key: repeat Steps 1-3 with a new keypair, then confirm the
  old private key file is deleted from the server once the new one is
  verified working (Step 4).

#  Copyright (c) 2026. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
"""
WhiteBooks.in GSP provider — implements gsp_provider.GSPProvider.

Replaces gsp_session.py's TaxPro/Charteredinfo cert-based session auth and
einv.py/eway_bill_api.py's ASP-ID+password headers with an OAuth2
client_credentials flow per docs/designs/gst-asp-migration-whitebooks.md,
Premise 2. **Revised 2026-08-22**: WhiteBooks issues a SEPARATE client_id/
client_secret pair per API product (e-Invoice, Public GST, e-Way Bill), each
with its own sandbox/production pair — not one shared pair across all three
as Premise 2 originally assumed. The OAuth2 mechanism (grant_type,
token-request shape) is still the same across all three families; only the
credentials — and therefore the cached token — are per-family. The shared
`Rohit Settings.sandbox_mode` checkbox still selects environment for all
three, reused rather than duplicated per family.

CONFIRMED 2026-08-22 (WhiteBooks' "GST-API" Postman collection, provided by
the user — covers the Public GST + GST-returns-filing product only):
PUBLIC_GST does **not** use OAuth2 at all. There is no token endpoint for
this family — every call sends `client_id`/`client_secret` directly as
request headers (see `get_static_client_headers()` below), plus a
registered account `email` as a query param (`Rohit Settings.
whitebooks_gst_email`). The `/oauth/token` 404 the live sandbox returned
("No API configured for :/oauth/token") is exactly this — PUBLIC_GST was
wrongly being routed through the OAuth2 flow below. get_headers()/get_token()
must NOT be used for PUBLIC_GST; call sites use get_static_client_headers()
instead. Base URL confirmed as apisandbox.whitebooks.in/api.whitebooks.in
(same host as the other families) but with NO per-family path prefix —
paths are rooted directly (e.g. `/public/search`, not `/gst/public/search`).

UNVERIFIED ASSUMPTIONS for EINVOICE and EWAY (see The Assignment in the
design doc — a sandbox auth handshake must confirm these before this module
is trusted in production for those two families; the Postman collection
above only covers PUBLIC_GST, not e-Invoice IRN generation or e-Way Bill):
1. Token endpoint path and grant_type/client_id/client_secret payload shape
   below follow the standard OAuth2 client_credentials convention. WhiteBooks'
   public docs describe OAuth2 bearer-token auth (confirmed via WebSearch,
   2026-08-22) but the exact token endpoint path was not in the pages
   fetched during that search. Given PUBLIC_GST turned out to use no OAuth2
   at all, treat this as genuinely unverified, not just unconfirmed detail —
   EINVOICE/EWAY may turn out to be static-header auth too.
2. Base URLs for the e-Invoice and e-Way Bill families are confirmed from
   WhiteBooks' own developer-portal pages (sandbox: apisandbox.whitebooks.in,
   production: api.whitebooks.in).
3. Whether each API family's token endpoint lives under that family's own
   path (e.g. .../einvoice/oauth/token) or a shared host-level path
   (.../oauth/token, disambiguated only by which client_id is presented) is
   unconfirmed. This module assumes the latter (a shared host-level token
   endpoint) since that's the more common OAuth2 client_credentials pattern
   — verify and adjust _fetch_new_token() if WhiteBooks' actual docs say
   otherwise.
"""
from datetime import datetime

import frappe
import requests

TIMEOUT = 15
DEFAULT_TOKEN_VALIDITY_SEC = 3600

EINVOICE = "einvoice"
EWAY = "eway"
PUBLIC_GST = "gst"
API_FAMILIES = (EINVOICE, EWAY, PUBLIC_GST)

_SANDBOX_HOST = "https://apisandbox.whitebooks.in"
_PRODUCTION_HOST = "https://api.whitebooks.in"
_API_PATHS = {
    EINVOICE: "/einvoice",
    EWAY: "/eway",
    PUBLIC_GST: "",  # confirmed 2026-08-22 — paths are rooted (/public/search), no /gst prefix
}
# Per-family Rohit Settings fieldname prefixes (whitebooks_<prefix>_client_id,
# ..._client_secret, ..._sandbox_client_id, ..._sandbox_client_secret).
_CREDENTIAL_FIELD_PREFIX = {
    EINVOICE: "whitebooks_einv",
    EWAY: "whitebooks_eway",
    PUBLIC_GST: "whitebooks_gst",
}


def _get_settings():
    return frappe.get_single("Rohit Settings")


def _validate_api_name(api_name):
    if api_name not in API_FAMILIES:
        frappe.throw(
            f"Unknown WhiteBooks API family {api_name!r} — expected one of {API_FAMILIES}"
        )


def get_base_url(api_name):
    """Base URL for the named API family, sandbox- or production-scoped per
    Rohit Settings.sandbox_mode — same environment-selection pattern
    common.get_base_url() already uses for the Charteredinfo/TaxPro flow."""
    _validate_api_name(api_name)
    rset = _get_settings()
    host = _SANDBOX_HOST if bool(rset.sandbox_mode) else _PRODUCTION_HOST
    return host + _API_PATHS[api_name]


def _token_cache_key(api_name):
    return f"whitebooks_gsp_access_token_{api_name}"


def _get_client_credentials(rset, api_name):
    prefix = _CREDENTIAL_FIELD_PREFIX[api_name]
    if bool(rset.sandbox_mode):
        client_id = getattr(rset, f"{prefix}_sandbox_client_id")
        client_secret = rset.get_password(f"{prefix}_sandbox_client_secret")
    else:
        client_id = getattr(rset, f"{prefix}_client_id")
        client_secret = rset.get_password(f"{prefix}_client_secret")
    if not client_id or not client_secret:
        env = "sandbox" if bool(rset.sandbox_mode) else "production"
        frappe.throw(
            f"WhiteBooks {env} client_id/client_secret for {api_name!r} are not "
            "configured on Rohit Settings — set them under the WhiteBooks GSP section."
        )
    return client_id, client_secret


def _fetch_new_token(rset, api_name):
    client_id, client_secret = _get_client_credentials(rset, api_name)
    # Token endpoint assumed shared at the host level, not scoped under each
    # family's own path — see module docstring, assumption 3.
    host = _SANDBOX_HOST if bool(rset.sandbox_mode) else _PRODUCTION_HOST
    url = host + "/oauth/token"
    body = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }
    resp = requests.post(url, data=body, timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    access_token = data.get("access_token")
    if not access_token:
        frappe.throw(f"WhiteBooks OAuth2 token request returned no access_token: {data}")

    expires_in = int(data.get("expires_in") or DEFAULT_TOKEN_VALIDITY_SEC)
    token = {
        "access_token": access_token,
        "token_type": data.get("token_type", "Bearer"),
        "fetched_at": datetime.now().isoformat(),
        "expires_in": expires_in,
    }
    # Cache a little short of the real expiry so a request never starts
    # against a token that's about to lapse mid-flight.
    cache_ttl = max(expires_in - 30, 30)
    frappe.cache().set_value(_token_cache_key(api_name), token, expires_in_sec=cache_ttl)
    return token


def get_token(api_name, force_refresh=False):
    """Returns a cached (or freshly fetched) WhiteBooks OAuth2 access token
    dict, scoped to the named API family's own client_id/client_secret."""
    _validate_api_name(api_name)
    if not force_refresh:
        cached = frappe.cache().get_value(_token_cache_key(api_name))
        if cached:
            return cached
    return _fetch_new_token(_get_settings(), api_name)


def get_headers(api_name):
    """Auth headers for a call to the named WhiteBooks API family, using
    that family's own token (per-family credentials, per Premise 2's
    2026-08-22 revision)."""
    token = get_token(api_name)
    return {
        "Authorization": f"{token['token_type']} {token['access_token']}",
        "Content-Type": "application/json",
    }


def get_static_client_headers(api_name):
    """Auth headers for API families that send client_id/client_secret
    directly on every call instead of exchanging them for an OAuth2 bearer
    token — confirmed 2026-08-22 for PUBLIC_GST via WhiteBooks' GST-API
    Postman collection (no /oauth/token endpoint exists for this family).
    Do not use get_headers()/get_token() for PUBLIC_GST."""
    rset = _get_settings()
    client_id, client_secret = _get_client_credentials(rset, api_name)
    return {"client_id": client_id, "client_secret": client_secret}


def get_registered_email(api_name):
    """The WhiteBooks account email registered against a family's
    client_id/client_secret — required as a query param on every PUBLIC_GST
    call (Rohit Settings.whitebooks_gst_email)."""
    prefix = _CREDENTIAL_FIELD_PREFIX[api_name]
    rset = _get_settings()
    email = getattr(rset, f"{prefix}_email", None)
    if not email:
        frappe.throw(
            f"WhiteBooks registered email for {api_name!r} is not configured "
            "on Rohit Settings — set it under the WhiteBooks GSP section."
        )
    return email


def refresh_session(api_name=None):
    """Drop the cached token for the named family — call after a 401/
    expired-token response, then retry the request once. Mirrors
    gsp_session.invalidate_session(). api_name is required for the
    per-family cache; kept as a defaulted kwarg only so this still matches
    gsp_provider.GSPProvider's zero-arg refresh_session() signature — call
    sites in this module always pass api_name explicitly."""
    if api_name is None:
        frappe.throw("whitebooks_provider.refresh_session() requires api_name")
    _validate_api_name(api_name)
    frappe.cache().delete_value(_token_cache_key(api_name))


def call_with_token_retry(request_fn, api_name):
    """Call request_fn() (a zero-arg callable making the actual HTTP call
    with fresh get_headers(api_name)) and retry it exactly once if the
    response indicates an expired/invalid token.

    request_fn must return a requests.Response. This is the single retry
    pattern from the Error Handling section of the design doc — one retry
    after invalidating, not an open-ended loop. Non-auth failures (5xx,
    timeouts, malformed bodies) are NOT retried here; they fail loud so the
    caller's own tagged logging (whitebooks-defect vs whitebooks-outage)
    can record them.
    """
    response = request_fn()
    if response.status_code == 401:
        refresh_session(api_name)
        response = request_fn()
    return response

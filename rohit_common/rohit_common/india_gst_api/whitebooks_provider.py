#  Copyright (c) 2026. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
"""
WhiteBooks.in GSP provider: base URLs, credentials, the response envelope, and
the authenticated e-Invoice and e-Way Bill clients.

WhiteBooks issues a separate client_id/client_secret pair per API product
(e-Invoice, Public GST, e-Way Bill), each with a sandbox and a production pair.
Every call sends them as headers. No family uses OAuth2.

CONFIRMED from WhiteBooks' Postman collections (E-INVOICE-API, E-waybill and
GST-API zips):
- e-Invoice: GET /einvoice/authenticate?email= with the headers username,
  password, ip_address, client_id, client_secret and gstin returns the
  AuthToken. Data calls go to /einvoice/type/<TYPE>/version/V1_03?email= with
  the headers username, auth-token, ip_address, client_id, client_secret and
  gstin.
- e-Way Bill: GET /ewaybillapi/v1.03/authenticate?email=&username=&password=
  opens a session that WhiteBooks keeps. Data calls go to
  /ewaybillapi/v1.03/ewayapi/<action>?email= with only ip_address, client_id,
  client_secret and gstin.
- Public GST / GST returns: rooted paths (/public/search), no family prefix.
- Every reply is {"status_cd", "status_desc", "error", "data"}.

UNVERIFIED until the first sandbox run of whitebooks_sandbox_probe.py (then
remove this note): the AuthToken/TokenExpiry field names, the e-Invoice
success status_cd spelling, and the token-expired error codes below.
"""
import json
from urllib.parse import urlparse

import frappe
import requests
from frappe.utils import cint, get_datetime, now_datetime

from .common import is_developer_mode

TIMEOUT = 30

EINVOICE = "einvoice"
EWAY = "eway"
PUBLIC_GST = "gst"
API_FAMILIES = (EINVOICE, EWAY, PUBLIC_GST)
# Families that create legal documents on the GST system. On a developer_mode
# site they always use the sandbox (common.use_gst_sandbox()).
DOCUMENT_API_FAMILIES = (EINVOICE, EWAY)

_SANDBOX_HOST = "https://apisandbox.whitebooks.in"
_PRODUCTION_HOST = "https://api.whitebooks.in"
_API_PATHS = {
    EINVOICE: "/einvoice",
    EWAY: "/ewaybillapi/v1.03",
    PUBLIC_GST: "",
}
# Per-family Rohit Settings fieldname prefixes (whitebooks_<prefix>_client_id,
# ..._client_secret, ..._sandbox_client_id, ..._sandbox_client_secret).
_CREDENTIAL_FIELD_PREFIX = {
    EINVOICE: "whitebooks_einv",
    EWAY: "whitebooks_eway",
    PUBLIC_GST: "whitebooks_gst",
}

EINVOICE_VERSION = "V1_03"
# WhiteBooks e-Invoice replies spell success "Sucess"; the other families use "1".
SUCCESS_STATUS = frozenset({"1", "Sucess", "Success"})
# NIC "invalid or expired token" codes. After one of these, authenticate again and
# resend once.
EINVOICE_AUTH_ERROR_CODES = frozenset({"1005"})
EWAY_AUTH_ERROR_CODES = frozenset({"238"})
# The e-Way Bill session lasts 6 hours. Re-open it a little earlier.
EWAY_SESSION_SECS = 350 * 60
EINVOICE_DEFAULT_TOKEN_SECS = 350 * 60


def _get_settings():
    return frappe.get_single("Rohit Settings")


def _validate_api_name(api_name):
    if api_name not in API_FAMILIES:
        frappe.throw(
            f"Unknown WhiteBooks API family {api_name!r} — expected one of {API_FAMILIES}"
        )


def _use_sandbox(rset, api_name):
    """Rohit Settings.sandbox_mode, forced on for document families in
    developer_mode — same rule as common.use_gst_sandbox()."""
    if api_name in DOCUMENT_API_FAMILIES and is_developer_mode():
        return True
    return bool(rset.sandbox_mode)


def get_base_url(api_name):
    """Base URL for the named API family, sandbox- or production-scoped per
    _use_sandbox()."""
    _validate_api_name(api_name)
    rset = _get_settings()
    host = _SANDBOX_HOST if _use_sandbox(rset, api_name) else _PRODUCTION_HOST
    return host + _API_PATHS[api_name]


def _get_client_credentials(rset, api_name):
    prefix = _CREDENTIAL_FIELD_PREFIX[api_name]
    sandbox = _use_sandbox(rset, api_name)
    if sandbox:
        client_id = getattr(rset, f"{prefix}_sandbox_client_id")
        client_secret = rset.get_password(f"{prefix}_sandbox_client_secret", raise_exception=False)
    else:
        client_id = getattr(rset, f"{prefix}_client_id")
        client_secret = rset.get_password(f"{prefix}_client_secret", raise_exception=False)
    if not client_id or not client_secret:
        env = "sandbox" if sandbox else "production"
        frappe.throw(
            f"WhiteBooks {env} client_id/client_secret for {api_name!r} are not "
            "configured on Rohit Settings — set them in the WhiteBooks GST section."
        )
    return client_id, client_secret


def get_static_client_headers(api_name):
    """client_id/client_secret headers that every WhiteBooks call sends."""
    rset = _get_settings()
    client_id, client_secret = _get_client_credentials(rset, api_name)
    return {"client_id": client_id, "client_secret": client_secret}


def get_registered_email(api_name=None):
    """The WhiteBooks account email. Every call sends it as the `email` query
    param. One account owns the client pairs of all families."""
    email = _get_settings().whitebooks_gst_email
    if not email:
        frappe.throw("Set WhiteBooks Registered Email in Rohit Settings (WhiteBooks GST section)",
                     title="WhiteBooks Email Missing")
    return email


# ---------------------------------------------------------------------------
# Response envelope, shared by every family
# ---------------------------------------------------------------------------


def is_success(resp):
    return str(resp.get("status_cd")) in SUCCESS_STATUS


def error_codes(resp):
    """Every error code in a reply, as strings. GSTN uses error_cd, WhiteBooks
    uses errorCode, and e-Invoice puts an IRP list of {ErrorCode, ErrorMessage}
    as JSON text in status_desc. e-Way Bill puts {"errorCodes": "238,"} in
    error.message."""
    codes = []
    error = resp.get("error")
    if isinstance(error, dict):
        codes += [error.get(key) for key in ("errorCode", "error_cd", "code")]
        codes += _codes_from_text(error.get("message"))
    else:
        codes += [resp.get("errorCode"), resp.get("error_cd")]
        codes += _codes_from_text(error)
    codes += _codes_from_text(resp.get("status_desc"))
    return [str(code).strip() for code in codes if code not in (None, "")]


def _codes_from_text(text):
    if not isinstance(text, str) or text[:1] not in "[{":
        return []
    try:
        parsed = json.loads(text)
    except ValueError:
        return []
    if isinstance(parsed, dict):
        return [code for code in str(parsed.get("errorCodes") or "").split(",") if code.strip()]
    if isinstance(parsed, list):
        return [row.get("ErrorCode") for row in parsed if isinstance(row, dict)]
    return []


def describe(resp):
    error = resp.get("error")
    message = (error.get("errorMessage") or error.get("message") or error.get("desc")
               if isinstance(error, dict) else error)
    return f"{resp.get('status_desc') or message or ''} (raw response: {resp})"


def unwrap(resp, context):
    """The `data` of a successful reply, parsed if WhiteBooks sends it as JSON text.
    Throws with the codes and the raw reply otherwise."""
    if not is_success(resp):
        frappe.throw(f"{context} failed: {describe(resp)}", title="WhiteBooks API Error")
    data = resp.get("data")
    if isinstance(data, str) and data[:1] in "[{":
        data = json.loads(data)
    return data


# ---------------------------------------------------------------------------
# e-Invoice and e-Way Bill clients
# ---------------------------------------------------------------------------


def get_document_session(api_name):
    """GSTIN, API user, client pair, email and IP for an e-Invoice or e-Way Bill
    call. The sandbox uses its own seller GSTIN. GST API Username/Password hold the
    user of the environment the site uses; in the sandbox it may be empty, and then
    no user is sent."""
    rset = _get_settings()
    sandbox = _use_sandbox(rset, api_name)
    gstin = rset.whitebooks_sandbox_gstin if sandbox else rset.gstin
    username = rset.eway_bill_id
    password = rset.get_password("eway_bill_password", raise_exception=False)
    env = "Sandbox" if sandbox else "Production"
    if not gstin or (not sandbox and not (username and password)):
        field = "Sandbox GSTIN" if sandbox else "GSTIN, GST API Username and GST API Password"
        frappe.throw(f"Set the {field} in Rohit Settings (WhiteBooks GST section)",
                     title="WhiteBooks GST API User Missing")
    if not rset.whitebooks_gst_ip_address:
        frappe.throw("Set WhiteBooks Server IP Address in Rohit Settings (WhiteBooks GST section)",
                     title="WhiteBooks IP Address Missing")
    client_id, client_secret = _get_client_credentials(rset, api_name)
    return frappe._dict(
        api_name=api_name, env=env, gstin=gstin, username=username, password=password,
        email=get_registered_email(api_name), base_url=get_base_url(api_name),
        headers={"client_id": client_id, "client_secret": client_secret,
                 "ip_address": rset.whitebooks_gst_ip_address, "gstin": gstin},
    )


def einvoice_request(method, type_, params=None, body=None, extra_headers=None):
    """One e-Invoice API call. Returns the reply envelope, so the caller can see
    error codes such as a duplicate IRN. Re-authenticates once on an expired token."""
    session = get_document_session(EINVOICE)
    url = f"{session.base_url}/type/{type_}/version/{EINVOICE_VERSION}"

    def send():
        headers = dict(session.headers, **_api_user(session, with_password=False))
        headers["auth-token"] = _einvoice_auth_token(session)
        headers.update(extra_headers or {})
        return _send(method, url, headers, dict(params or {}, email=session.email), body)

    resp = send()
    if set(error_codes(resp)) & EINVOICE_AUTH_ERROR_CODES:
        frappe.cache().delete_value(_cache_key(session, "einv_token"))
        resp = send()
    return resp


def eway_request(method, action, params=None, body=None):
    """One e-Way Bill API call. Returns the reply envelope. Opens the WhiteBooks
    session first, and once more if WhiteBooks says it expired."""
    session = get_document_session(EWAY)
    url = f"{session.base_url}/ewayapi/{action}"

    def send():
        _open_eway_session(session)
        return _send(method, url, session.headers, dict(params or {}, email=session.email), body)

    resp = send()
    if set(error_codes(resp)) & EWAY_AUTH_ERROR_CODES:
        frappe.cache().delete_value(_cache_key(session, "eway_session"))
        resp = send()
    return resp


def _cache_key(session, kind):
    return f"whitebooks_{kind}:{session.env}:{session.gstin}"


def _api_user(session, with_password=True):
    """username (and password) of the GST API user, leaving out what is not set"""
    user = {"username": session.username}
    if with_password:
        user["password"] = session.password
    return {key: value for key, value in user.items() if value}


def _einvoice_auth_token(session):
    key = _cache_key(session, "einv_token")
    token = frappe.cache().get_value(key)
    if token:
        return token
    headers = dict(session.headers, **_api_user(session))
    resp = _send("GET", f"{session.base_url}/authenticate", headers, {"email": session.email})
    data = unwrap(resp, f"WhiteBooks e-Invoice authentication for GSTIN {session.gstin}") or {}
    token = data.get("AuthToken")
    if not token:
        frappe.throw(f"WhiteBooks e-Invoice authentication returned no AuthToken: {describe(resp)}",
                     title="WhiteBooks API Error")
    frappe.cache().set_value(key, token, expires_in_sec=_token_secs(data.get("TokenExpiry")))
    return token


def _token_secs(token_expiry):
    """Seconds to cache the token: until 2 minutes before TokenExpiry."""
    if not token_expiry:
        return EINVOICE_DEFAULT_TOKEN_SECS
    secs = int((get_datetime(token_expiry) - now_datetime()).total_seconds()) - 120
    return max(secs, 60)


def _open_eway_session(session):
    key = _cache_key(session, "eway_session")
    if cint(frappe.cache().get_value(key)):
        return
    params = dict(_api_user(session), email=session.email)
    resp = _send("GET", f"{session.base_url}/authenticate", session.headers, params)
    unwrap(resp, f"WhiteBooks e-Way Bill authentication for GSTIN {session.gstin}")
    frappe.cache().set_value(key, 1, expires_in_sec=EWAY_SESSION_SECS)


def _send(method, url, headers, params, body=None):
    """Sends a request and returns the JSON reply. A network error is raised
    without the URL: the e-Way Bill authenticate URL holds the API password (#23)."""
    kwargs = {"data": body} if isinstance(body, str) else {"json": body}
    error = None
    try:
        response = requests.request(method, url, headers=dict(headers, **{"Content-Type": "application/json"}),
                                    params=params, timeout=TIMEOUT, **kwargs)
        reply = response.json()
    except requests.RequestException as e:
        error = type(e).__name__
    except ValueError:
        error = f"HTTP {response.status_code}, reply is not JSON"
    # Throw outside the except block, so the traceback does not chain the
    # original exception and its URL.
    if error:
        frappe.throw(f"WhiteBooks request to {urlparse(url).path} failed: {error}",
                     title="WhiteBooks Request Failed")
    return reply

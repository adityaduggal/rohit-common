#  Copyright (c) 2022. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
"""
WhiteBooks.in GST taxpayer API: the per-GSTIN OTP session, and GSTR1 / GSTR2A /
GSTR2B downloads. The TaxPro/Charteredinfo version put the ASP password in the
query string. It was replaced 2026-10-27.

CONFIRMED from WhiteBooks' "WB-GST-API" Postman collection (GST API.postman_collection.zip):
- Same product, base URL (no path prefix) and client_id/client_secret pair as the
  Public GST family (whitebooks_provider.PUBLIC_GST).
- Every call sends the headers client_id, client_secret, gst_username, state_cd and
  ip_address. Every call except /authentication/otprequest also sends txn.
- Every call takes the registered account `email` as a query param.
- Paths: /authentication/{otprequest,authtoken,refreshtoken},
  /gstr1/<section>?gstin=&retperiod=, /gstr2a/<section>?gstin=&retperiod=,
  /gstr2b/all?gstin=&rtnprd=&filenum=.

UNVERIFIED ASSUMPTIONS (the collection has no 200 response bodies; confirm them on
the first sandbox call, then remove this note):
1. /authentication/otprequest returns the session id as header.txn (or a top-level
   txn). See _extract_txn().
2. Data calls return {"status_cd": "1", "data": {<section key>: [...]}}, which is
   the same envelope /public/rettrack uses. See _unwrap().
3. "No data for this section/period" comes back as status_cd "0" with one of
   NO_DATA_ERROR_CODES. CONFIRMED 2026-10-27 for RET11416 on a production GSTR1 b2cl
   call: {"status_cd": "0", "error": {"errorCode": ..., "errorMessage": ...}}.
   See _error_code().
Every failure message includes the raw response, so a wrong guess shows its real
shape on the first live call.
"""
import datetime

import frappe
import requests
from frappe.utils import cint, get_datetime, now_datetime

from . import whitebooks_provider

TIMEOUT = 30
API_NAME = whitebooks_provider.PUBLIC_GST
REGISTRATION_DOCTYPE = "GST Registration Details"
# GSTN issues the taxpayer auth token for 6 hours.
TOKEN_VALIDITY_MINS = 360
# UNVERIFIED (3) - GSTN "no invoices/documents found" error codes.
NO_DATA_ERROR_CODES = frozenset({"RET13510", "RET13509", "RET11416", "RET11417", "RET2B1016"})
# Errors after which a refresh can't recover the session. The user must request
# a new OTP. Carried over from the TaxPro implementation.
REVOKE_ACCESS_ERROR_CODES = frozenset({"AUTH4037", "RET11402", "SWEB9033", "AUTH4033", "GSP102"})


def get_gstr1(gstin: str, ret_period: str, sections: dict) -> dict:
    """Download several GSTR1 sections. See _get_return_sections()."""
    return _get_return_sections("gstr1", gstin, ret_period, sections)


def get_gstr2a(gstin: str, ret_period: str, sections: dict) -> dict:
    """Download several GSTR2A sections. See _get_return_sections()."""
    return _get_return_sections("gstr2a", gstin, ret_period, sections)


def get_gstr2b(gstin: str, ret_period: str) -> dict:
    """
    GSTR2B for a period as {"data": GSTN payload}. Callers read response["data"]["gendt"/"docdata"].
    A large GSTR2B comes back as a file count ("fc"); then every file is fetched and the docdata
    sections are joined.
    """
    reg = get_registration(gstin)
    assert_session_active(reg)
    session = _session(reg)
    context = f"GSTR2B for GSTIN {gstin}, period {ret_period}"
    params = {"gstin": gstin, "rtnprd": ret_period}
    payload = _gstr2b_payload(_get(session, "/gstr2b/all", params), context)
    file_count = cint(payload.get("fc"))
    if file_count and not payload.get("gendt"):
        files = [_gstr2b_payload(_get(session, "/gstr2b/all", dict(params, filenum=str(num))), context)
                 for num in range(1, file_count + 1)]
        payload = _join_gstr2b_files(files)
    if not payload.get("gendt"):
        frappe.throw(f"{context}: the reply has no generation date (gendt). Payload keys: {sorted(payload)}",
                     title="WhiteBooks GSTR2B Reply Not Recognised")
    return {"data": payload}


def _gstr2b_payload(resp, context):
    """The GSTN GSTR2B payload. WhiteBooks wraps GSTN's own {"data": {...}} in its "data" key."""
    if not _is_success(resp):
        frappe.throw(f"{context} failed: {_describe(resp)}", title="WhiteBooks GSTR2B Error")
    payload = resp.get("data")
    while isinstance(payload, dict) and "gendt" not in payload and "fc" not in payload \
            and isinstance(payload.get("data"), dict):
        payload = payload["data"]
    if not isinstance(payload, dict):
        frappe.throw(f"{context}: reply has no data. Raw response: {resp}",
                     title="WhiteBooks GSTR2B Reply Not Recognised")
    return payload


def _join_gstr2b_files(files):
    joined = dict(files[0], docdata={})
    for part in files:
        for section, rows in (part.get("docdata") or {}).items():
            joined["docdata"].setdefault(section, []).extend(rows or [])
        joined["gendt"] = joined.get("gendt") or part.get("gendt")
    return joined


@frappe.whitelist()
def get_gst_otp(gstin):
    """Ask GSTN to send an OTP to the GSTIN's registered mobile/email. This starts
    a new WhiteBooks session (txn), so the old session is no longer authorized."""
    frappe.has_permission("Rohit GST Settings", "write", throw=True)
    gstin = _require_str("GSTIN", gstin)
    reg = get_registration(gstin)
    resp = _get(_session(reg, with_txn=False), "/authentication/otprequest", {})
    if not _is_success(resp):
        frappe.throw(f"OTP request for GSTIN {gstin} failed: {_describe(resp)}",
                     title="WhiteBooks OTP Request Failed")
    txn = _extract_txn(resp)
    if not txn:
        frappe.throw(f"WhiteBooks accepted the OTP request for GSTIN {gstin} but returned no txn. "
                     f"Raw response: {resp}", title="WhiteBooks OTP Response Not Recognised")
    frappe.db.set_value(REGISTRATION_DOCTYPE, reg.name, {
        "whitebooks_txn": txn, "otp": "", "api_access_authorized": 0, "authorization_token": ""})
    frappe.msgprint(f"OTP sent for GSTIN {gstin}. Enter the OTP received on the registered mobile number "
                    "and click Validate OTP.")


@frappe.whitelist()
def authenticate_gst_otp(gstin, otp, row_id):
    frappe.has_permission("Rohit GST Settings", "write", throw=True)
    gstin = _require_str("GSTIN", gstin)
    otp = _require_str("OTP", otp)
    row_id = _require_str("Row ID", row_id)
    if not otp.isdigit():
        frappe.throw(f"OTP must contain only digits. Received {otp!r}", title="Invalid OTP")
    reg = get_registration(gstin)
    if reg.name != row_id:
        frappe.throw(f"Row {row_id} is not the Rohit GST Settings row for GSTIN {gstin}",
                     title="GSTIN and Row Mismatch")
    if not reg.whitebooks_txn:
        frappe.throw(f"No OTP was requested for GSTIN {gstin}. Click Request OTP first.",
                     title="OTP Not Requested")
    resp = _get(_session(reg), "/authentication/authtoken", {"otp": otp})
    if not _is_success(resp):
        frappe.throw(f"OTP validation for GSTIN {gstin} failed: {_describe(resp)}",
                     title="WhiteBooks OTP Validation Failed")
    now = now_datetime()
    frappe.db.set_value(REGISTRATION_DOCTYPE, reg.name, {
        "api_access_authorized": 1,
        "authorization_token": _extract_auth_token(resp),
        "validity_of_token": now + datetime.timedelta(minutes=TOKEN_VALIDITY_MINS),
        "last_otp_sent": now,
        "no_of_times_token_updated": 0,
        "otp": "",
    })
    frappe.msgprint(f"API access for GSTIN {gstin} is now active")


def check_for_refresh_token(row):
    """Scheduler entry: extend the session for one Rohit GST Settings row before
    it expires. Failures are logged, not thrown, so one GSTIN's failure does not
    stop the others."""
    if cint(row.api_access_authorized) != 1 or not row.whitebooks_txn or not row.validity_of_token:
        return
    now = now_datetime()
    validity = get_datetime(row.validity_of_token)
    if now >= validity:
        frappe.db.set_value(REGISTRATION_DOCTYPE, row.name, {"api_access_authorized": 0, "otp": ""})
        return
    refresh_after = validity - datetime.timedelta(minutes=TOKEN_VALIDITY_MINS) + \
        datetime.timedelta(minutes=cint(row.update_token_every_mins))
    if now < refresh_after:
        return
    resp = _get(_session(row), "/authentication/refreshtoken", {})
    if _is_success(resp):
        frappe.db.set_value(REGISTRATION_DOCTYPE, row.name, {
            "validity_of_token": now + datetime.timedelta(minutes=TOKEN_VALIDITY_MINS),
            "authorization_token": _extract_auth_token(resp) or row.authorization_token,
            "no_of_times_token_updated": cint(row.no_of_times_token_updated) + 1,
        })
        return
    if _error_code(resp) in REVOKE_ACCESS_ERROR_CODES:
        frappe.db.set_value(REGISTRATION_DOCTYPE, row.name, {"api_access_authorized": 0, "otp": ""})
    frappe.log_error(f"GSTIN {row.gst_registration_number}: {_describe(resp)}",
                     "WhiteBooks GST Token Refresh Failed")


def get_registration(gstin: str) -> frappe._dict:
    """The Rohit GST Settings row for a GSTIN, read with one query."""
    rows = frappe.get_all(
        REGISTRATION_DOCTYPE,
        filters={"parenttype": "Rohit GST Settings", "gst_registration_number": gstin},
        fields=["name", "gst_registration_number", "gst_username", "api_access_authorized",
                "authorization_token", "validity_of_token", "whitebooks_txn",
                "no_of_times_token_updated", "update_token_every_mins"],
    )
    if not rows:
        frappe.throw(f"GSTIN {gstin} is not set up in Rohit GST Settings for API access",
                     title="GSTIN Not Registered for GST API")
    if len(rows) > 1:
        frappe.throw(f"GSTIN {gstin} is in Rohit GST Settings {len(rows)} times. Remove the duplicate rows.",
                     title="Duplicate GSTIN in Rohit GST Settings")
    reg = rows[0]
    if not reg.gst_username:
        frappe.throw(f"GST Username for GSTIN {gstin} is empty in Rohit GST Settings",
                     title="GST Username Missing")
    return reg


def assert_session_active(reg: frappe._dict) -> None:
    if (cint(reg.api_access_authorized) != 1 or not reg.whitebooks_txn or not reg.validity_of_token
            or get_datetime(reg.validity_of_token) <= now_datetime()):
        frappe.throw(f"GST API access for GSTIN {reg.gst_registration_number} is not authorized or has "
                     "expired. Use Request OTP and Validate OTP in Rohit GST Settings.",
                     title="GST API Authorization Expired")


def get_invoice_type(itype):
    """
    Returns the Invoice Type for a Invoice Type code
    """
    inv_type_txt = ""
    if itype == "R":
        inv_type_txt = "R-Regular B2B Invoices"
    elif itype == "DE":
        inv_type_txt = "DE-Deemed Exports"
    elif itype == "SEWP":
        inv_type_txt = "SEWP-SEZ Exports with payment"
    elif itype == "SEWOP":
        inv_type_txt = "SEWOP-SEZ exports without payment"
    return inv_type_txt


def get_type_of_amend(amend_type):
    """
    Returns text for a the Type of Amend to the Invoice for a Code
    """
    amd_type_txt = ""
    if amend_type == "R":
        amd_type_txt = "R-Receiver GSTIN Amended"
    elif amend_type == "N":
        amd_type_txt = "N-Invoice Number Amended"
    elif amend_type == "D":
        amd_type_txt = "D-Details Amended"
    return amd_type_txt


def _get_return_sections(return_type, gstin, ret_period, sections):
    """sections maps the WhiteBooks path segment (e.g. "txp") to the key GSTN
    uses for that section in the response (e.g. "txpd"). Returns {path segment:
    rows}. There are no DB writes, so a caller can fetch everything before it
    changes anything."""
    reg = get_registration(gstin)
    assert_session_active(reg)
    session = _session(reg)
    result = {}
    for path, response_key in sections.items():
        resp = _get(session, f"/{return_type}/{path}", {"gstin": gstin, "retperiod": ret_period})
        result[path] = _unwrap(resp, response_key, context=f"{return_type.upper()} {path} for "
                                                           f"GSTIN {gstin}, period {ret_period}")
    return result


def _session(reg, with_txn=True):
    """Everything a call for this GSTIN needs, built once per batch of calls."""
    ip_address = frappe.db.get_single_value("Rohit Settings", "whitebooks_gst_ip_address", cache=False)
    if not ip_address:
        frappe.throw("Set GST Returns API Server IP Address in Rohit Settings (WhiteBooks section)",
                     title="WhiteBooks IP Address Missing")
    headers = whitebooks_provider.get_static_client_headers(API_NAME)
    headers.update({
        "gst_username": reg.gst_username,
        "state_cd": reg.gst_registration_number[:2],
        "ip_address": ip_address,
    })
    if with_txn:
        if not reg.whitebooks_txn:
            frappe.throw(f"No WhiteBooks session for GSTIN {reg.gst_registration_number}. "
                         "Use Request OTP in Rohit GST Settings.", title="GST API Session Missing")
        headers["txn"] = reg.whitebooks_txn
    return frappe._dict(
        base_url=whitebooks_provider.get_base_url(API_NAME),
        headers=headers,
        email=whitebooks_provider.get_registered_email(API_NAME),
    )


def _get(session, path, params):
    response = requests.get(
        url=session.base_url + path,
        headers=session.headers,
        params=dict(params, email=session.email),
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def _is_success(resp):
    return str(resp.get("status_cd")) == "1"


def _error_code(resp):
    # GSTN uses error_cd; WhiteBooks replies use errorCode.
    error = resp.get("error")
    if isinstance(error, dict):
        return error.get("errorCode") or error.get("error_cd")
    return resp.get("errorCode") or resp.get("error_cd")


def _describe(resp):
    error = resp.get("error")
    message = error.get("errorMessage") or error.get("message") if isinstance(error, dict) else error
    return f"{resp.get('status_desc') or message or ''} (raw response: {resp})"


def _extract_txn(resp):
    # UNVERIFIED (1)
    header = resp.get("header")
    if isinstance(header, dict) and header.get("txn"):
        return header["txn"]
    data = resp.get("data")
    if isinstance(data, dict) and data.get("txn"):
        return data["txn"]
    return resp.get("txn")


def _extract_auth_token(resp):
    # WhiteBooks may keep the GSTN auth token on its side and key it by txn.
    # Store it when it is returned. Nothing here sends it back.
    data = resp.get("data")
    if isinstance(data, dict) and data.get("auth_token"):
        return data["auth_token"]
    return resp.get("auth_token") or ""


def _unwrap(resp, response_key, context):
    if _is_success(resp):
        # UNVERIFIED (2)
        data = resp.get("data")
        payload = data if isinstance(data, dict) else resp
        return payload.get(response_key) or []
    if _error_code(resp) in NO_DATA_ERROR_CODES:
        return []
    frappe.throw(f"{context} failed: {_describe(resp)}", title="WhiteBooks GST Returns API Error")


def _require_str(label, value):
    # Type-check at the trust boundary: a whitelisted arg can arrive as a
    # list/dict (e.g. ["!=", ""]) and turn into a filter.
    if not isinstance(value, str) or not value.strip():
        frappe.throw(f"{label} must be a non-empty text value", title="Invalid GST API Input")
    return value.strip()

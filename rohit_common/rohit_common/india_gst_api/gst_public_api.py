#  Copyright (c) 2021. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
"""
WhiteBooks.in Public GST API (GSTIN search / return tracking / GSTR1 data).

Migrated from TaxPro/Charteredinfo (gsp_session.py, deleted 2026-08-22 once
this path was verified end to end — cert-based GetKey session auth, now
replaced by WhiteBooks' static client_id/client_secret header auth) per
docs/designs/gst-asp-migration-whitebooks.md, T4.

CONFIRMED 2026-08-22 against WhiteBooks' "GST-API" Postman collection
(user-provided) and a real sandbox+production round trip: endpoint paths
are /public/search and /public/rettrack (rooted, no /gst prefix), auth is
client_id/client_secret sent as request headers on every call
(whitebooks_provider.get_static_client_headers() — no OAuth2 bearer token
for this family), and every call additionally requires a registered
account `email` query param (Rohit Settings.whitebooks_gst_email).
status_cd is a string present on both outcomes ("1" success / "0" failure).

get_gstr1_whitebooks() (added 2026-08-26, /plan-eng-review of
gstr1_return_rigpl/) is UNVERIFIED — see its own docstring below. It
replaces the legacy TaxPro-based india_gst_api/gst_api.py's get_gstr1(),
which is left in place, unused by gstr1_return_rigpl.py, pending this
function's real sandbox verification (same gradual-cutover posture as the
rest of this migration — Premise 4 only requires deleting old code once the
replacement is verified, not before).
"""
import frappe
import datetime
from frappe.utils import getdate
from . import whitebooks_provider
import requests
timeout = 15


def search_gstin_whitebooks(gstin=None):
    rset = frappe.get_single("Rohit Settings")
    caller_gstin = rset.gstin
    search_gstin_value = gstin or caller_gstin
    api_name = whitebooks_provider.PUBLIC_GST

    response = requests.get(
        url=whitebooks_provider.get_base_url(api_name) + "/public/search",
        headers=whitebooks_provider.get_static_client_headers(api_name),
        params={
            "email": whitebooks_provider.get_registered_email(api_name),
            "gstin": search_gstin_value,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def track_return_whitebooks(gstin, fiscal_year, type_of_return=None):
    fy_format = fiscal_year[:5] + fiscal_year[7:]
    api_name = whitebooks_provider.PUBLIC_GST
    params = {
        "email": whitebooks_provider.get_registered_email(api_name),
        "gstin": gstin,
        "fy": fy_format,
    }
    if type_of_return:
        params["type"] = type_of_return

    response = requests.get(
        url=whitebooks_provider.get_base_url(api_name) + "/public/rettrack",
        headers=whitebooks_provider.get_static_client_headers(api_name),
        params=params,
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def get_gstr1_whitebooks(gstin, ret_period, action):
    """GSTR1 return-data retrieval (per-action sub-tables: B2B, B2CL, CDNR,
    HSNSUM, etc. — see gstr1_actions in gstr1_return_rigpl.py) via
    WhiteBooks.

    UNVERIFIED — replaces india_gst_api/gst_api.py's TaxPro-based
    get_gstr1(), which hit a completely different, ASP-ID+password-auth'd
    endpoint (/taxpayerapi/dec/{version}/returns/gstr1) that was never part
    of this app's WhiteBooks migration. Three separate assumptions here,
    each needing a real sandbox call to confirm before this is trusted for
    actual GSTR1 reconciliation:

    1. **Auth/product**: assumed to be the same PUBLIC_GST family (static
       client_id/client_secret headers + registered email) as
       search_gstin_whitebooks()/track_return_whitebooks() above, since
       docs/designs/gst-asp-migration-whitebooks.md (T4) describes
       WhiteBooks' "GST-API" Postman collection as covering "Public GST +
       GST-returns-filing" as one product — but the collection's confirmed
       example calls only covered /public/search and /public/rettrack, not
       a GSTR1-data endpoint. If GST-returns-filing turns out to be a
       separate WhiteBooks product with its own client_id/client_secret,
       this needs a new API family in whitebooks_provider.py, not this one.
    2. **Endpoint path**: assumed /returns/gstr1 (rooted, no /gst prefix —
       same no-prefix convention already confirmed for /public/search and
       /public/rettrack under this family).
    3. **Response envelope**: assumed a dict keyed by lowercase action code
       (e.g. {"b2b": [...]}), matching the legacy TaxPro get_gstr1()'s
       contract that gstr1_return_rigpl.py's process_gstr1() already
       depends on via resp.get(action.lower()) — kept as-is here so that
       call site needs no changes. status_cd handling mirrors the string
       "1"/"0" convention already confirmed for this family's other two
       endpoints.

    The `action`/`gstin`/`ret_period` param names themselves are the GSTN
    Taxpayer API's own standard names (used industry-wide across GSPs, not
    TaxPro-specific — see the legacy common.py get_api_version() table's
    identical "returns/gstr1" action path), so these three are
    higher-confidence than the endpoint/auth/envelope assumptions above.
    """
    api_name = whitebooks_provider.PUBLIC_GST
    response = requests.get(
        url=whitebooks_provider.get_base_url(api_name) + "/returns/gstr1",
        headers=whitebooks_provider.get_static_client_headers(api_name),
        params={
            "email": whitebooks_provider.get_registered_email(api_name),
            "gstin": gstin,
            "ret_period": ret_period,
            "action": action,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    resp = response.json()
    status_cd = str(resp.get("status_cd", ""))
    if status_cd == "1":
        pass
    elif resp.get(action.lower()) is not None:
        pass
    elif status_cd == "0":
        return {}
    else:
        frappe.throw(f"WhiteBooks GSTR1 fetch failed for action={action}, period={ret_period}: {resp}")
    return resp


def get_arn_status(ret_status_json, type_of_return, ret_period):
    arn, status, dof, mof = "", "", "", ""
    found = 0
    efiled_list = ret_status_json.get('EFiledlist')
    if efiled_list:
        for d in efiled_list:
            if type_of_return == d.get("rtntype") and ret_period == d.get("ret_prd"):
                found = 1
                arn = d.get("arn")
                status = d.get("status")
                dof = getdate(d.get("dof"))
                mof = d.get("mof")
                break
        if found != 1:
            frappe.msgprint(f"No Filing Data found for {type_of_return} for Period: {ret_period}")
    else:
        frappe.msgprint("No eFiling Data Received")
    return arn, status, dof, mof

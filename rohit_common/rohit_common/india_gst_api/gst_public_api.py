#  Copyright (c) 2021. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
import frappe
import datetime
from frappe.utils import getdate
from . import gsp_session
from . import whitebooks_provider
import requests
timeout = 15


def _get_with_session_retry(build_url, action, gstin, extra_params=None):
    """GET a Public API endpoint, retrying once with a forced session refresh
    if the request comes back REQUEST_DENIED (stale/invalidated session)."""
    for attempt in (1, 2):
        api = gsp_session.build_public_api_headers(action=action, gstin=gstin)
        url = build_url(api["base_url"])
        try:
            response = requests.get(url=url, headers=api["headers"], timeout=timeout)
            json_response = response.json()
        except Exception as e:
            frappe.throw(f"Some Error Occurred calling TaxPro GSP Public API and the Error is {e}")
        if json_response.get("status") == "REQUEST_DENIED" and attempt == 1:
            gsp_session.invalidate_session()
            continue
        return json_response
    return json_response


def search_gstin(gstin=None):
    rset = frappe.get_single("Rohit Settings")
    caller_gstin = rset.gstin

    def build_url(base_url):
        return (
            base_url + "/commonapi/v1.1/search?Action=TP"
            + "&Gstin=" + caller_gstin
            + "&SearchGstin=" + (gstin or caller_gstin)
        )

    return _get_with_session_retry(build_url, action="TP", gstin=caller_gstin)


def track_return(gstin, fiscal_year, type_of_return=None):
    fy_format = fiscal_year[:5] + fiscal_year[7:]

    def build_url(base_url):
        url = base_url + "/commonapi/v1.0/returns?Action=RETTRACK&Gstin=" + gstin + "&fy=" + fy_format
        if type_of_return:
            url += "&type=" + type_of_return
        return url

    return _get_with_session_retry(build_url, action="RETTRACK", gstin=gstin)


# ---------------------------------------------------------------------------
# WhiteBooks.in equivalents (T4, docs/designs/gst-asp-migration-whitebooks.md)
#
# NOT YET WIRED INTO THE LIVE CALL PATH, and gsp_session.py is NOT deleted
# yet — per Premise 4, cutover (swap live call sites + delete gsp_session.py)
# waits until a real WhiteBooks sandbox call confirms the response shape
# assumed below. search_gstin()/track_return() above remain the current
# (broken) production path until then.
#
# UNVERIFIED RESPONSE SHAPE: endpoint paths ("/gstin-search", "/return-track")
# are placeholders — WhiteBooks' Public GST API docs (confirmed via
# WebSearch, 2026-08-22) mention "GSTIN verification (single and bulk), HSN
# code search, and SAC code lookup" as capabilities but not exact paths.
# track_return_whitebooks()'s response is assumed to still use the EFiledlist
# shape get_arn_status() already parses below, since that shape looks like
# GSTN's own return-status schema (rtntype/ret_prd/arn/status/dof/mof), not
# something TaxPro-specific — consistent with Premise 3 (vendors pass through
# the government schema) but not directly confirmed for WhiteBooks. Confirm
# both against a real sandbox response before trusting this in production.
# ---------------------------------------------------------------------------


def search_gstin_whitebooks(gstin=None):
    """WhiteBooks.in equivalent of search_gstin(). See module note above."""
    rset = frappe.get_single("Rohit Settings")
    caller_gstin = rset.gstin
    search_gstin_value = gstin or caller_gstin

    def _call():
        return requests.get(
            url=whitebooks_provider.get_base_url(whitebooks_provider.PUBLIC_GST) + "/gstin-search",
            headers=whitebooks_provider.get_headers(whitebooks_provider.PUBLIC_GST),
            params={"gstin": search_gstin_value},
            timeout=timeout,
        )

    response = whitebooks_provider.call_with_token_retry(_call, whitebooks_provider.PUBLIC_GST)
    response.raise_for_status()
    return response.json()


def track_return_whitebooks(gstin, fiscal_year, type_of_return=None):
    """WhiteBooks.in equivalent of track_return(). See module note above."""
    fy_format = fiscal_year[:5] + fiscal_year[7:]
    params = {"gstin": gstin, "fy": fy_format}
    if type_of_return:
        params["type"] = type_of_return

    def _call():
        return requests.get(
            url=whitebooks_provider.get_base_url(whitebooks_provider.PUBLIC_GST) + "/return-track",
            headers=whitebooks_provider.get_headers(whitebooks_provider.PUBLIC_GST),
            params=params,
            timeout=timeout,
        )

    response = whitebooks_provider.call_with_token_retry(_call, whitebooks_provider.PUBLIC_GST)
    response.raise_for_status()
    return response.json()


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

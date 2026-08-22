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
# NOT YET WIRED INTO THE LIVE CALL PATH by default — gsp_session.py is NOT
# deleted — but validate_gstin_from_portal() (validations/address.py) was
# deliberately cut over to search_gstin_whitebooks() on 2026-08-22 for live
# sandbox testing, ahead of the general "wait until verified" rule, since
# gsp_session.py's TaxPro decrypt was already broken and blocking testing.
#
# CONFIRMED 2026-08-22 against WhiteBooks' "GST-API" Postman collection
# (user-provided): endpoint paths are /public/search and /public/rettrack
# (rooted, no /gst prefix), auth is client_id/client_secret sent as request
# headers on every call (get_static_client_headers() — no OAuth2 bearer
# token for this family, see whitebooks_provider.py's module docstring), and
# every call additionally requires a registered account `email` query param
# (Rohit Settings.whitebooks_gst_email).
#
# RESPONSE SHAPE still unverified: the search/rettrack response bodies
# themselves have not yet been seen from a real sandbox call.
# track_return_whitebooks()'s response is assumed to still use the
# EFiledlist shape get_arn_status() already parses below, since that shape
# looks like GSTN's own return-status schema (rtntype/ret_prd/arn/status/
# dof/mof) that a GSP would pass through per Premise 3 — not yet confirmed
# for WhiteBooks specifically.
# ---------------------------------------------------------------------------


def search_gstin_whitebooks(gstin=None):
    """WhiteBooks.in equivalent of search_gstin(). See module note above."""
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
    """WhiteBooks.in equivalent of track_return(). See module note above."""
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

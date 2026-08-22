#  Copyright (c) 2021. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
"""
WhiteBooks.in Public GST API (GSTIN search / return tracking).

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

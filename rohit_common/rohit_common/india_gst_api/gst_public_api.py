#  Copyright (c) 2021. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
import frappe
import datetime
from frappe.utils import getdate
from . import gsp_session
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

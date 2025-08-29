#  Copyright (c) 2021. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
import frappe
import datetime
from frappe.utils import getdate
from .common import get_gsp_details
import requests
timeout = 5


def search_gstin(gstin=None):
    gsp_link, asp_id, asp_pass, caller_gstin, sandbox = get_gsp_details(api_type="common", action='TP', api='search')
    if not gstin:
        gstin = caller_gstin
    full_url = gsp_link + '&Gstin=' + caller_gstin + '&SearchGstin=' + gstin
    try:
        response = requests.get(url=full_url, timeout=timeout)
    except Exception as e:
        frappe.throw(f"Some Error Occurred while Searching for GSTIN {gstin} and the Error is {e}")
    json_response = response.json()
    return json_response


def track_return(gstin, fiscal_year, type_of_return=None):
    # (fiscal_year, start_date, end_date) = get_fiscal_year(for_date)
    fy_format = fiscal_year[:5] + fiscal_year[7:]
    gsp_link, asp_id, asp_pass, caller_gstin, sandbox = get_gsp_details(api_type="common", action='RETTRACK',
                                                                        api="returns")
    if type_of_return:
        full_url = gsp_link + '&Gstin=' + gstin + '&FY=' + fy_format + '&type=' + type_of_return
    else:
        full_url = gsp_link + '&Gstin=' + gstin + '&FY=' + fy_format
    response = requests.get(url=full_url, timeout=timeout)
    # frappe.throw(str(response.text))
    json_response = response.json()
    # frappe.throw(str(json_response))
    return json_response


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

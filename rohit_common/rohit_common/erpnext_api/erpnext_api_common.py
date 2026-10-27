#  Copyright (c) 2021. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
import json
import frappe
import requests
timeout = 5


def get_login_details():
    base_link = ""
    auth_header = ""
    rset = frappe.get_cached_doc("Rohit Settings")
    if rset.api_key:
        auth_header = {"Authorization": "token " + rset.api_key + ":" + rset.api_secret}
        base_link = rset.erpnext_app_base_link
    else:
        print(f"No Settings for ERP API Exiting")
    return base_link, auth_header


def get_dt(dt, dt_name=None, fields_list=None, filters=None):
    """
    Returns the JSON from the ERP's /api/resource for `dt`, or None when the ERP API is not set.
    Raises requests.HTTPError on an error status and ValueError when the body is not JSON.
    `filters` is a list of lists.
    """
    base_url, auth_header = get_login_details()
    if not base_url:
        return None
    link = base_url + "/api/resource/" + dt
    if dt_name:
        link += "/" + dt_name
    params = {}
    if fields_list:
        params["fields"] = json.dumps(fields_list)
    if filters:
        params["filters"] = json.dumps(filters)
    r = requests.get(url=link, headers=auth_header, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()

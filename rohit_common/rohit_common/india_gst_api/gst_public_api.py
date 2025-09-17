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
    # Debug logging for asp_secret value
    # Debug logging for encryption diagnostics (mask sensitive info)
    # (fiscal_year, start_date, end_date) = get_fiscal_year(for_date)
    fy_format = fiscal_year[:5] + fiscal_year[7:]
    gsp_link, asp_id, asp_pass, caller_gstin, sandbox, session_id, asp_ek = get_gsp_details(api_type="common", action='RETTRACK', api="returns")
    print(f"[GSTAPI DEBUG] tax_pro_asp_secret (len={len(asp_pass)}): {asp_pass[:8]}...{asp_pass[-8:]}")
    if not session_id:
        frappe.throw("Session ID could not be generated. Please check DSC and API credentials.")
    # Encrypt asp_pass using AspEK (asp_ek) as per TaxPro GSP requirements
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
    import base64

    # Decode asp_ek and ensure it's 32 bytes for AES-256
    key_bytes = base64.b64decode(asp_ek)
    if len(key_bytes) > 32:
        key_bytes = key_bytes[:32]
    elif len(key_bytes) < 32:
        # Pad key to 32 bytes if needed (shouldn't happen, but for safety)
        key_bytes = key_bytes.ljust(32, b'\0')
    cipher = AES.new(key_bytes, AES.MODE_ECB)
    # Base64 decode asp_pass (Asp Secret Key) before encryption, as per TaxPro GSP sample
    payload = base64.b64decode(asp_pass)
    padded = pad(payload, AES.block_size)
    encrypted = cipher.encrypt(padded)
    asp_secret_encrypted = base64.b64encode(encrypted).decode('utf-8')
    print(f"[GSTAPI DEBUG] asp_ek (len={len(asp_ek)}): {asp_ek[:8]}...{asp_ek[-8:]}")
    print(f"[GSTAPI DEBUG] asp_pass (len={len(asp_pass)}): {asp_pass[:2]}...{asp_pass[-2:]}")
    print(f"[GSTAPI DEBUG] asp_secret_encrypted (len={len(asp_secret_encrypted)}): {asp_secret_encrypted[:8]}...{asp_secret_encrypted[-8:]}")

    if type_of_return:
        full_url = gsp_link + '&Gstin=' + gstin + '&FY=' + fy_format + '&type=' + type_of_return
    else:
        full_url = gsp_link + '&Gstin=' + gstin + '&FY=' + fy_format
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "asp-secret": asp_secret_encrypted,
        "session-id": session_id,
        "aspid": asp_id,
        "txn": str(datetime.datetime.now().timestamp()).replace('.', ''),
        "GSTIN": gstin ,
        "ip-usr": "127.0.0.1"
    }
    response = requests.get(url=full_url, headers=headers, timeout=timeout)
    json_response = response.json()
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

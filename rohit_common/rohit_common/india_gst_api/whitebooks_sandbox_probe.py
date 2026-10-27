#  Copyright (c) 2026. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
"""
Records real WhiteBooks sandbox replies for the e-Invoice and e-Way Bill calls,
to confirm the UNVERIFIED notes in whitebooks_provider.py, einv.py and
eway_bill_api.py. Sandbox only. It saves nothing on the invoice. Tokens, keys
and passwords are masked in the output.

    bench --site dev-rb-v12 execute \\
        rohit_common.rohit_common.india_gst_api.whitebooks_sandbox_probe.run \\
        --kwargs "{'sales_invoice': 'SINV-XXXX'}"

Without sales_invoice it only authenticates. With it, it also generates the IRN
twice (the second reply is the duplicate), looks the IRN up by number and by
document, generates the e-Way Bill from the IRN and reads it back.
"""
import json
import re

import frappe
from frappe.utils import getdate

from . import whitebooks_provider as wb
from .common import use_gst_sandbox
from .einv import gen_einv_json, get_eway_details, get_einv_doctype

SECRET_KEYS = re.compile(r"token|sek|password|secret", re.I)
LONG_KEYS = ("SignedInvoice", "SignedQRCode")


def run(sales_invoice=None):
    if not use_gst_sandbox():
        frappe.throw("The probe only runs in the sandbox (Sandbox Mode or developer_mode)")
    replies = {}
    einv = wb.get_document_session(wb.EINVOICE)
    frappe.cache().delete_value(wb._cache_key(einv, "einv_token"))
    headers = dict(einv.headers, username=einv.username, password=einv.password)
    replies["einvoice authenticate"] = wb._send(
        "GET", f"{einv.base_url}/authenticate", headers, {"email": einv.email})

    eway = wb.get_document_session(wb.EWAY)
    frappe.cache().delete_value(wb._cache_key(eway, "eway_session"))
    replies["eway authenticate"] = wb._send("GET", f"{eway.base_url}/authenticate", eway.headers,
        {"email": eway.email, "username": eway.username, "password": eway.password})

    if sales_invoice:
        payload = gen_einv_json("Sales Invoice", sales_invoice)
        replies["GENERATE"] = wb.einvoice_request("POST", "GENERATE", body=payload)
        replies["GENERATE again (duplicate)"] = wb.einvoice_request("POST", "GENERATE", body=payload)
        irn = (_data(replies["GENERATE"]) or {}).get("Irn")
        if irn:
            replies["GETIRN"] = wb.einvoice_request("GET", "GETIRN", params={"param1": irn})
        doc = frappe.get_doc("Sales Invoice", sales_invoice)
        replies["GETIRNBYDOCDETAILS"] = wb.einvoice_request(
            "GET", "GETIRNBYDOCDETAILS", params={"param1": get_einv_doctype(doc)},
            extra_headers={"docnum": doc.name, "docdate": getdate(doc.posting_date).strftime("%d/%m/%Y")})
        if irn:
            body = dict(get_eway_details("Sales Invoice", sales_invoice), Irn=irn)
            replies["GENERATE_EWAYBILL"] = wb.einvoice_request("POST", "GENERATE_EWAYBILL", body=body)
            ewb_no = (_data(replies["GENERATE_EWAYBILL"]) or {}).get("EwbNo")
            if ewb_no:
                replies["getewaybill"] = wb.eway_request("GET", "getewaybill", params={"ewbNo": ewb_no})
    print(json.dumps(_mask(replies), indent=1, default=str))


def _data(resp):
    data = resp.get("data")
    if isinstance(data, str) and data[:1] in "[{":
        data = json.loads(data)
    return data if isinstance(data, dict) else None


def _mask(value, key=""):
    if isinstance(value, dict):
        return {k: _mask(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask(v) for v in value]
    if isinstance(value, str) and value[:1] in "[{":
        try:
            return _mask(json.loads(value), key)
        except ValueError:
            pass
    if isinstance(value, str) and SECRET_KEYS.search(key):
        return f"<masked, {len(value)} chars>"
    if isinstance(value, str) and key in LONG_KEYS:
        return f"{value[:20]}... <{len(value)} chars>"
    return value

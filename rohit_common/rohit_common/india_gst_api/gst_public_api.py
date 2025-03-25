#  Copyright (c) 2021. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
import os
import frappe
import datetime
from frappe.utils import getdate, get_files_path
from .common import get_gsp_details
import requests
timeout = 5


import base64
import requests
import datetime
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from functools import lru_cache


def load_private_key_from_pfx(pfx_path, pfx_password):
    with open(pfx_path, 'rb' as f:
        pfx_data = f.read()

    private_key, certificate, additional_certificates = pkcs12.load_key_and_certificates(
        pfx_data,
        pfx_password.encode() if pfx_password else None
    )

    return private_key


def sign_data(private_key, data):
    signature = private_key.sign(
        data.encode(),
        padding.PKCS1v15(),
        hashes.SHA256()
    )
    return base64.b64encode(signature).decode()


def decrypt_enc_key(enc_key_b64, asp_password):
    key = asp_password.encode()
    cipher = AES.new(key, AES.MODE_ECB)
    decrypted = cipher.decrypt(base64.b64encode(enc_key_b64))
    return unpad(decrypted, AES.block_size).decode()


def get_current_timestamp():
    now = datetime.datetime.utcnow()
    return now.strftime('%d%m%Y%H:%H:%S:%f')[:20]


@lru_cache()
def get_key(
    asp_id,
    asp_password,
    pfx_path,
    pfx_password,
    tnx,
    ip_usr,
    env='sandbox'):

    urls = {
        'sandbox': 'https://gstsandbox.charteredinfo.com/aspapi/v1.0/getKey',
        'production': 'https://gstapi.charteredinfo.com/aspapi/v1.0/getKey'
    }

    timestamp = get_current_timestamp()
    data_to_sign = aspid + timestamp

    private_key = load_private_key_from_pfx(pfx_path, pfx_password)
    signed_content = sign_data(private_key, data_to_sign)

    headers = {
        'aspid': aspid,
        'txn': txn,
        'ip-usr': ip_usr,
        'Content-Type': 'application/json; charset=utf-8',
    }

    body = {
        'timestamp': timestamp,
        'signed_content': signed_content
    }

    response = requests.post(urls[env], headers=headers, json=body)
    result = response.json()

    if result.get('status_cd') != '1':
        raise Exception(f"GetKey API Error: {result.get('message')}")

    decrypted_key = decrypt_enc_key(result['enc_key'], asp_password)

    return {
        'session_id': result['session_id'],
        'asp_ek': decrypted_key,
        'validity_min': result['validity_min'],
        'txn': result['txn']
    }

@lru_cache()
def get_public_ip():
    return requests.get('https://api.ipify.org').content.decode('utf-8')


def get_headers():
    import rohit_common
    settings = frappe.get_doc('Rohit Settings', 'Rohit Settings')

    pfx_path = get_files_path(is_private=True, os.path.basename(settings.cert_pfx))

    return {
        'aspid': settings.tax_pro_asp_id,
        'asp-secret': get_key(
            asp_id=settings.tax_pro_asp_id,
            asp_password=settings.tax_pro_password,
            pfx_path=pfx_path,
            pfx_password=settings.tax_pro_password,
            tnx='tnx-'+datetime.datetime.isoformat('T'),
            ip_usr=get_public_ip()
        ),
        'tnx': 'tnx-'+datetime.datetime.isoformat('T'),
        'appver': rohit_common.__version__,
        'Content-Type': 'application/json; charset=utf-8',
        'ip-usr': get_public_ip()
    }


def search_gstin(gstin=None):
    #import pdb; pdb.set_trace()
    gsp_link, asp_id, asp_pass, caller_gstin, sandbox = get_gsp_details(api_type="common", action='TP', api='search')
    if not gstin:
        gstin = caller_gstin
    full_url = gsp_link + '&Gstin=' + caller_gstin + '&SearchGstin=' + gstin
    try:
        response = requests.get(url=full_url, timeout=timeout, header=get_headers())
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
        fraeppe.msgprint("No eFiling Data Received")
    return arn, status, dof, mof

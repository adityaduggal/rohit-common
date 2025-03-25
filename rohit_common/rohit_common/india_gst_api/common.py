#  Copyright (c) 2021. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
import frappe
from datetime import datetime
from frappe.utils import flt, get_last_day, getdate


def get_place_of_supply(dtype, dname):
    """
    Returns Integer Value for Place of Supply Based on Following Rules
    1. For Sales Invoice Return State code of the Buyer
    2. For Purchase Order Return the State code for the Billing Address
    """
    doc = frappe.get_doc(dtype, dname)
    if dtype == "Sales Invoice":
        country = frappe.get_value("Address", doc.customer_address, "country")
        if country == "India":
            state = frappe.get_value("Address", doc.customer_address, "state")
        else:
            pos = "96"
    elif dtype == "Purchase Order":
        country = frappe.get_value("Address", doc.billing_address, "country")
        if country == "India":
            state = frappe.get_value("Address", doc.billing_address, "state")
        else:
            pos = "96"
    else:
        frappe.throw("Unable to State Code")
    if country == "India":
        pos = frappe.get_value("State", state, "state_code_numeric")
    return pos


def get_gst_based_uom(uom):
    """
    Returns the UOM value based on GST if the UoM based on GST is not mentioned in the UoM Master
    then it return an error to update the UOM as per the master list from 2 URLs.
    URL1 (eway) = https://docs.ewaybillgst.gov.in/apidocs/master-codes-list.html
    URL2 (einvoice) = https://einvoice1.gst.gov.in/Others/MasterCodes
    """
    url1 = "https://docs.ewaybillgst.gov.in/apidocs/master-codes-list.html"
    url2 = "https://einvoice1.gst.gov.in/Others/MasterCodes"
    err_message = f"""There is NO GST UoM code mentioned for {uom}.\n
    Kindly refer URL for Eway = {url1} or \n
    URL for e-Invoice = {url2} and update the UoM Master"""
    gst_uom_code = frappe.get_value("UOM", uom, "eway_bill_uom")
    if not gst_uom_code:
        print(err_message)
        frappe.throw(err_message)
    return gst_uom_code


def get_gst_pincode(pincode, country="India"):
    """
    Returns pincode based on country and entered pincode
    If country is not India then returns 999999 as pincode
    """
    if country != "India":
        pincode = 999999
    else:
        pincode = int(pincode)
    return pincode


def get_numeric_state_code(state_name, country="India"):
    """
    Returns Integer for State Name for Indian State Code else returns 96 for Other Countries
    """
    if country != "India":
        state_code = "96"
    else:
        state_code = frappe.get_value("State", state_name, "state_code_numeric")
    return state_code


def get_default_gstin(sbox=0):
    """
    Returns the default gstin mentioned in the Settings
    """
    rset = frappe.get_doc("Rohit Settings", "Rohit Settings")
    if sbox == 0:
        def_gstin = rset.gstin
    else:
        def_gstin = rset.gstin

    return def_gstin


def get_base_url(sbox=0):
    """
    Returns the Base GST URL and Sandbox status as Integer in Settings
    """
    rset = frappe.get_doc("Rohit Settings", "Rohit Settings")
    if sbox == 0:
        # If the sandbox mode is default to ZERO then checks if Sbox is active in settings
        sbox = rset.sandbox_mode
    if sbox == 0:
        api_link = rset.api_link
    else:
        api_link = rset.sandbox_api_link
    return api_link, sbox


def get_aspid_pass():
    """
    Returns the asp user ID and password
    """
    rset = frappe.get_doc("Rohit Settings", "Rohit Settings")
    aspid = rset.tax_pro_asp_id
    asppass = rset.tax_pro_password

    return aspid, asppass


def get_api_version(api):
    api_version_list = [
        {"api": "search", "version": "v1.1", "action": "TP"},
        {"api": "returns", "version": "v1.0", "action": "TP"},
        {"api": "asp", "version": "v1.0", "action": "TP"},
        {"api": "eway", "version": "v1.03", "action": "TP"},
        {"api": "search", "version": "v1.1", "action": "TP"},
        {"api": "otp", "version": "v1.0", "action": "authenticate"},
        {"api": "doc", "version": "v1.1", "action": "document"},
        {"api": "doc_det", "version": "v1.1", "action": "returns"},
        {"api": "gstr1_ret_status", "version": "v0.2", "action": "returns/gstr1"},
        {"api": "gstr1", "version": "v2.1", "action": "returns/gstr1"},
        {"api": "gstr2a", "version": "v2.0", "action": "returns/gstr2a"},
        {"api": "gstr2b", "version": "v1.0", "action": "returns/gstr2b"},
        {"api": "einv", "version": "v1.0", "action": "returns/gstr2b"}
    ]
    for row in api_version_list:
        if row["api"] == api:
            return row["version"], row["action"]


def get_api_url(api, api_type=None):
    version, act_type = get_api_version(api)
    rset = frappe.get_single('Rohit Settings')
    if api_type == "common":
        api_url = '/' + api_type + 'api/' + version + '/' + api + '?'
    elif api == 'eway':
        if rset.sandbox_mode == 1:
            api_url = '/' + api + 'billapi/dec/' + version + '/'
        else:
            api_url = '/' + version + '/dec/'
    elif api == 'asp':
        api_url = '/' + api + 'api/' + version + '/'
    return api_url


def get_gsp_details(api, action, gstin=None, api_type=None):
    rset = frappe.get_single('Rohit Settings')
    sandbox = rset.sandbox_mode
    gsp_link = rset.api_link
    asp_id = rset.tax_pro_asp_id
    asp_pass = rset.tax_pro_password

    if api == 'eway':
        gsp_link = gsp_link[:8] + "einvapi." + gsp_link[8:]
    else:
        gsp_link = gsp_link[:8] + "gstapi." + gsp_link[8:]


    if not gstin:
        if api_type == 'common' and not sandbox:
            gstin = rset.gstin
        else:
            if sandbox == 1:
                gstin = '05AAACG1539P1ZH'
            else:
                gstin = rset.gstin

    gsp_sandbox_link = rset.sandbox_api_link
    api_url = '/' + api
    if api_type == "common":
        api_url = get_api_url(api=api, api_type=api_type)
    
    if rset.sandbox_mode == 1:
        gsp_link = gsp_sandbox_link
    
    if api_type == 'common':
        gsp_link = gsp_link + api_url + 'aspid=' + asp_id + '&password=' + asp_pass + '&Action=' + action

    return gsp_link, asp_id, asp_pass, gstin, sandbox


def gst_return_period_validation(return_period):
    month = flt(return_period[:2])
    year = flt(return_period[2:])
    now = datetime.now()
    message = f"Return Period Format is MMYYYY. {return_period} does not conform to that format"
    if len(return_period) != 6:
        frappe.throw(message)
    if month < 1 or month > 12:
        frappe.throw(message)
    if year < 2017 or year > now.year:
        frappe.throw("Year Cannot be in Future or Before 2017")
    elif year == 2017:
        if month < 7:
            frappe.throw("Return Period Cannot be Before July-2017")
    elif year == now.year:
        if month > now.month:
            frappe.throw("Return Period Can only be for Past or Current Months")


def get_dates_from_return_period(monthly_ret_pd):
    rt_year = monthly_ret_pd[2:]
    rt_month = monthly_ret_pd[:2]
    rt_fst_date = rt_year + "-" + rt_month + "-01"
    first_day = getdate(rt_fst_date)
    last_day = get_last_day(dt=first_day)
    return first_day, last_day


def validate_gstin(gstin):
    if len(gstin) != 15:
        frappe.throw(f"GST Number: {gstin} Should be of 15 Characters")

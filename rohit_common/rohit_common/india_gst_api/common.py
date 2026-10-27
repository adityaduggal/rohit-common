#  Copyright (c) 2021. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
import frappe
from datetime import datetime
from frappe.utils import cint, flt, get_last_day, getdate


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
    Returns the GSTIN the e-Invoice and e-Way Bill APIs act for: Rohit Settings.gstin,
    or the WhiteBooks sandbox GSTIN in the sandbox
    """
    field = "whitebooks_sandbox_gstin" if sbox else "gstin"
    def_gstin = frappe.db.get_single_value("Rohit Settings", field)
    if not def_gstin:
        frappe.throw(f"Set {frappe.unscrub(field)} in Rohit Settings", title="GSTIN Missing")
    return def_gstin


def is_developer_mode():
    """developer_mode from site_config.json or common_site_config.json."""
    return bool(cint(frappe.conf.get("developer_mode")))


def use_gst_sandbox(rset=None):
    """
    True if GST document APIs (e-Invoice, e-Way Bill) must use the sandbox:
    Rohit Settings.sandbox_mode is on, or the site runs in developer_mode.
    A developer or copied test site never sends documents to production GST,
    even when its copied Rohit Settings still say production.
    """
    if is_developer_mode():
        return True
    rset = rset or frappe.get_single("Rohit Settings")
    return bool(cint(rset.sandbox_mode))


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

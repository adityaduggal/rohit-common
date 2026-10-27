#  Copyright (c) 2022. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
"""
e-Invoice (IRN) generation on WhiteBooks.in, and the IRP payload builders.
Charteredinfo/TaxPro was removed 2026-10-27 (issues #17, #19). The request,
auth and reply envelope live in whitebooks_provider.einvoice_request().

UNVERIFIED until the first sandbox run of whitebooks_sandbox_probe.py: the
duplicate-IRN code (NIC uses 2150) and that GETIRNBYDOCDETAILS takes the doc
type as param1 and docnum/docdate as headers, as the Postman collection shows.
"""
import json
import frappe
from frappe.utils import cint, flt, getdate
from rq.timeouts import JobTimeoutException
from . import whitebooks_provider
from .eway_bill_api import get_taxes_type, get_transport_mode, get_eway_distance
from .common import get_default_gstin, get_numeric_state_code, get_gst_pincode, \
    get_gst_based_uom, get_place_of_supply, use_gst_sandbox
DUPLICATE_IRN_ERROR_CODE = "2150"
EWB_FAILURE_TITLE = "e-Way Bill from IRN Failed for "


def generate_irn(dtype, dname):
    """
    Generates the IRN for a Document No and a Document Type, and saves it with the
    signed QR code. IRN can be generated for the following documents only B2B
    1. Sales Invoice normal and credit notes based on items
    2. Journal Entry if Credit or Debit Notes for Registered Customers or Suppliers
    A duplicate IRN means the IRP already has one for this document, so it is
    fetched and saved instead. Any other rejection throws, so the 15-min sweep
    logs it and backs off this invoice (#16).
    """
    resp = whitebooks_provider.einvoice_request("POST", "GENERATE", body=gen_einv_json(dtype, dname))
    if whitebooks_provider.is_success(resp):
        irn_dict = whitebooks_provider.unwrap(resp, f"IRN generation for {dname}")
    elif DUPLICATE_IRN_ERROR_CODE in whitebooks_provider.error_codes(resp):
        irn_dict = get_irn_by_doc(dtype, dname)
    else:
        frappe.throw(f"IRN not generated for {dname}. {whitebooks_provider.describe(resp)}",
                     title="eInvoice Rejected")
    update_irn_details(dtype, dname, irn_dict)
    if auto_ewb_needed(dtype, dname):
        try:
            generate_ewb_by_irn(dname)
        except JobTimeoutException:
            raise
        except Exception:
            # The IRN is saved. The e-Way Bill can still be made by hand or pulled.
            frappe.db.rollback()
            frappe.log_error(frappe.get_traceback(), EWB_FAILURE_TITLE + dname)
            frappe.db.commit()


def get_irn_details(irn_no):
    """
    Gets IRN details (Irn, AckNo, AckDt, SignedQRCode, ...) for a given IRN number
    """
    resp = whitebooks_provider.einvoice_request("GET", "GETIRN", params={"param1": irn_no})
    return whitebooks_provider.unwrap(resp, f"IRN lookup for {irn_no}") or {}


def get_irn_by_doc(dtype, dname):
    """
    Gets the IRN details of a document by its type, number and date. Used after a
    duplicate IRN reply, which does not carry the signed QR code.
    """
    doc = frappe.get_doc(dtype, dname)
    resp = whitebooks_provider.einvoice_request(
        "GET", "GETIRNBYDOCDETAILS", params={"param1": get_einv_doctype(doc)},
        extra_headers={"docnum": dname, "docdate": getdate(doc.posting_date).strftime("%d/%m/%Y")})
    return whitebooks_provider.unwrap(resp, f"IRN lookup for {dname}") or {}


def update_irn_details(dtype, dname, irn_dict):
    """
    Saves the IRN No, Ack No, Ack Date and the signed QR code in a Doctype. The
    print formats draw the QR from signed_qr_code, so no PNG is made (#17).
    """
    qr_code = irn_dict.get("SignedQRCode")
    if not qr_code:
        qr_code = get_irn_details(irn_dict.get("Irn")).get("SignedQRCode")
    if not qr_code:
        # Nothing is saved, so the next sweep run gets a duplicate IRN reply and
        # fetches the IRN and QR code again.
        frappe.throw(f"IRP returned no Signed QR Code for {dname} (IRN {irn_dict.get('Irn')})",
                     title="eInvoice QR Code Missing")
    values = {
        "irn": irn_dict.get("Irn"),
        "ack_no": irn_dict.get("AckNo"),
        "ack_date": irn_dict.get("AckDt"),
        "signed_qr_code": qr_code,
    }
    if irn_dict.get("EwbNo"):
        values["ewaybill"] = str(irn_dict.get("EwbNo"))
    frappe.db.set_value(dtype, dname, values)
    # The IRP has issued the IRN and cannot take it back, so keep it even if the
    # caller rolls back later.
    frappe.db.commit()


def auto_ewb_needed(dtype, dname):
    """
    True if Rohit Settings asks for an e-Way Bill with each IRN, and the invoice is
    over the e-Way Bill limit and has none yet.
    """
    if dtype != "Sales Invoice":
        return False
    auto_ewb, eway_limit = frappe.db.get_value(
        "Rohit Settings", "Rohit Settings", ["auto_generate_ewb_from_irn", "eway_bill_limit"])
    if not cint(auto_ewb):
        return False
    total, ewaybill = frappe.db.get_value(dtype, dname, ["base_grand_total", "ewaybill"])
    return not ewaybill and flt(total) >= flt(eway_limit)


def generate_ewb_by_irn(dname):
    """
    Generates the e-Way Bill of a Sales Invoice from its IRN and saves the number
    in Sales Invoice.ewaybill
    """
    irn = frappe.db.get_value("Sales Invoice", dname, "irn")
    if not irn:
        frappe.throw(f"No IRN mentioned in {frappe.get_desk_link('Sales Invoice', dname)}")
    body = dict(get_eway_details("Sales Invoice", dname), Irn=irn)
    resp = whitebooks_provider.einvoice_request("POST", "GENERATE_EWAYBILL", body=body)
    ewb = whitebooks_provider.unwrap(resp, f"e-Way Bill from IRN for {dname}") or {}
    if not ewb.get("EwbNo"):
        frappe.throw(f"IRP returned no e-Way Bill number for {dname}: {whitebooks_provider.describe(resp)}")
    frappe.db.set_value("Sales Invoice", dname, "ewaybill", str(ewb.get("EwbNo")))
    frappe.db.commit()
    return ewb


def gen_einv_json(dtype, dname):
    """
    Generates and returns e-Invoice Json for a Given Doctype. Currently supported Doctypes are:
    1. Sales Invoice
    2. Journal Entry (For Credit and Debit Notes only)
    """
    einv_dt = frappe._dict({})
    # einv_dt."$schema" = "http://json-schema.org/draft-07/schema#"
    einv_dt.Title = "GST-India Invoice Document "
    einv_dt.Description = "GST Invoice format for IRN Generation in INDIA"
    einv_dt.Version = "1.1"
    dtd = frappe.get_doc(dtype, dname)
    pos = get_place_of_supply(dtype, dname)
    einv_dt = add_einv_doc_details(einv_dt, dtype, dname)
    sell_add = dtd.company_address
    buy_add = dtd.customer_address
    ship_add = dtd.shipping_address_name
    einv_dt = add_einv_adr_details(einv_dt, sell_add, type_of_detail="seller")
    if use_gst_sandbox():
        # The sandbox only accepts its own seller GSTIN
        einv_dt.SellerDtls.Gstin = get_default_gstin(sbox=1)
        einv_dt.SellerDtls.Stcd = einv_dt.SellerDtls.Gstin[:2]
    einv_dt = add_einv_adr_details(einv_dt, buy_add, type_of_detail="buyer", pos=pos)
    einv_dt = add_einv_adr_details(einv_dt, ship_add, type_of_detail="ship",
        port_code=dtd.port_code)
    einv_it_val = get_einv_item_details(dtype, dname)
    einv_dt.ItemList = einv_it_val[0]
    einv_dt.ValDtls = einv_it_val[1]
    # einv_final.Data = einv_dt
    einv_json = json.dumps(einv_dt)
    # Dispatch details are only needed when there is difference in Biller and dispatcher
    # einv_dt = add_einv_adr_details(einv_dt, sell_add, type_of_detail="dispatch")
    return einv_json


def get_eway_details(dtype, dname):
    """
    Returns a dictionary for eway Bill for Sales Invoice and Purchase Order and for JV its not
    needed since eway is not needed
    """
    eway_dt = frappe._dict({})
    sid = frappe.get_doc(dtype, dname)
    eway_dt.Distance = cint(sid.distance) or get_eway_distance(frm_adr_name=sid.company_address,
        to_adr_name=sid.shipping_address_name)
    eway_dt.TransMode = str(get_transport_mode(sid.mode_of_transport))
    tpt_gstin = get_transporter_gstin(sid.transporters)
    if tpt_gstin:
        eway_dt.TransId = tpt_gstin
        eway_dt.TransDocNo = sid.lr_no
        if sid.lr_date:
            eway_dt.TransDocDt = getdate(sid.lr_date).strftime("%d/%m/%Y")
    else:
        # Self pickup: the vehicle number was kept in lr_no before vehicle_no existed
        eway_dt.VehNo = sid.vehicle_no or sid.lr_no
        eway_dt.VehType = "R"
    return eway_dt


def get_transporter_gstin(tpt_name):
    """
    Returns the GSTIN for Transporter Name
    """
    tpt_gstin = frappe.get_value("Transporters", tpt_name, "gstin_for_eway")
    self_pickup = frappe.get_value("Transporters", tpt_name, "self_pickup")
    if self_pickup == 1:
        tpt_gstin = None
    else:
        if not tpt_gstin:
            frappe.throw(f"For {frappe.get_desk_link('Tranporters', {tpt_name})} EWay is Not \
                Possible since No GSTIN for Transporter is Mentioned")
    return tpt_gstin


def get_einv_item_details(dtype, dname):
    """
    Returns item details dictionary for the Einvoice Json based on following rules for RIGPL
    1. for Sales Invoice the Item Details is in synopsis to avoid showing itemwise price details
    2. For JV where there is no Qty involved the system automatically adds the item details
        2.1 Here the problem would come with the HSN code for items in case of JV for TOD (figure)
    """
    itm_lst = []
    val_dt = frappe._dict({})
    dtd = frappe.get_doc(dtype, dname)
    if dtype == "Sales Invoice":
        tax_details = get_taxes_type(dtype, dname)
        val_dt.AssVal = round(abs(tax_details.get("tax_val", 0)), 2)
        val_dt.TotInvVal = round(abs(tax_details.get("tot_val", 0)), 2)
        val_dt.CgstVal = round(abs(tax_details.get("cgst_amt", 0)), 2)
        val_dt.SgstVal = round(abs(tax_details.get("sgst_amt", 0)), 2)
        val_dt.IgstVal = round(abs(tax_details.get("igst_amt", 0)), 2)
        val_dt.Discount = round(abs(tax_details.get("discount_amt", 0)), 2)
        val_dt.OthChrg = round(abs(tax_details.get("other_amt", 0)), 2)
        gst_rate = tax_details.get("gst_per")
        for row in dtd.items:
            it_row_dict = frappe._dict({})
            hsn_doc = frappe.get_doc("GST HSN Code", row.gst_hsn_code)
            is_ser = flt(hsn_doc.is_service)
            if is_ser == 0:
                is_ser = "N"
            else:
                is_ser = "Y"
            it_row_dict.SlNo = str(row.idx)
            it_row_dict.PrdDesc = hsn_doc.description[:299]
            it_row_dict.IsServc = is_ser
            it_row_dict.HsnCd = row.gst_hsn_code
            it_row_dict.Qty = abs(row.qty)
            it_row_dict.Unit = get_gst_based_uom(row.uom)
            it_row_dict.UnitPrice = round(row.base_rate, 2)
            it_row_dict.TotAmt = round(abs(row.base_amount), 2)
            it_row_dict.AssAmt = round(abs(row.base_amount), 2)
            it_row_dict.GstRt = gst_rate
            it_row_dict.IgstAmt = abs(round(row.base_amount * (tax_details.get("igst_per", 0)/100),
                2))
            it_row_dict.CgstAmt = abs(round(row.base_amount * (tax_details.get("cgst_per", 0)/100),
                2))
            it_row_dict.SgstAmt = abs(round(row.base_amount * (tax_details.get("sgst_per", 0)/100),
                2))
            it_row_dict.TotItemVal = abs(round(row.base_amount * (1 + gst_rate/100), 2))
            itm_lst.append(it_row_dict)
    else:
        message = f"e-Invoice Not Supported for {dtype} and for the Doc No: {dname}"
        print(message)
        frappe.throw(message)
    return itm_lst, val_dt


def add_einv_adr_details(einv_dt, add_name, type_of_detail, pos=None, port_code=None):
    """
    Adds dictionary to e-Invoice dictionary and returns the updated dictionary
    einv_dt is the Base dictionary
    add_name = Address name from Address Doctype
    Type of Detail is whether seller, buyer, ship or dispatch
    Place of Supply is needed in case of Buyer details
    """
    adr_dict = get_einv_address_details(add_name)
    if type_of_detail == "seller":
        einv_dt.SellerDtls = adr_dict
    elif type_of_detail == "buyer":
        if not pos:
            message = "For Buyer details we need Place of Supply"
            print(message)
            frappe.throw(message)
        adr_dict.Pos = pos
        einv_dt.BuyerDtls = adr_dict
    elif type_of_detail == "dispatch":
        adr_dict.Nm = adr_dict.LglNm
        einv_dt.DispDtls = adr_dict
    elif type_of_detail == "ship":
        add_doc = frappe.get_doc("Address", add_name)
        if add_doc.country != "India":
            if not port_code:
                ps_message = "Port Code is Mandatory for Export Transactions"
                print(ps_message)
                frappe.throw(ps_message)
            else:
                einv_dt.ShipDtls = adr_dict
    else:
        message = f"Type of Detail {type_of_detail} is Not Compatible"
        print(message)
        frappe.throw(message)
    return einv_dt


def get_einv_address_details(add_name):
    """
    Returns the dictionary for an Address Name for e-Invoice
    """
    adr_dict = frappe._dict({})
    add_doc = frappe.get_doc("Address", add_name)
    if add_doc.country != "India":
        adr_dict.Gstin = "URP"
    else:
        if add_doc.gstin == "NA":
            adr_dict.Gstin = "URP"
        else:
            adr_dict.Gstin = add_doc.gstin
    adr_dict.LglNm = add_doc.address_title
    if len(add_doc.address_line1) < 1:
        message = f"For {frappe.get_desk_link('Address', add_name)} Address Line 1 is Missing"
        print(message)
        frappe.throw(message)
    adr_dict.Addr1 = add_doc.address_line1[:99]
    if add_doc.address_line2 and len(add_doc.address_line2) > 2:
        adr_dict.Addr2 = add_doc.address_line2[:99]
    st_code = get_numeric_state_code(state_name=add_doc.state, country=add_doc.country)
    pincode = get_gst_pincode(add_doc.pincode, add_doc.country)
    adr_dict.Stcd = st_code
    adr_dict.Pin = pincode
    if len(add_doc.city) > 2:
        adr_dict.Loc = add_doc.city[:49]
    else:
        message = f"For {frappe.get_desk_link('Address', add_name)} City is Missing"
        print(message)
        frappe.throw(message)
    '''
    # ToDo Add email only after validations for emails are added in Address or Doctype
    if add_doc.email_id and len(add_doc.email_id) > 5:
        adr_dict.Em = add_doc.email_id[:99]
    '''
    return adr_dict


def add_einv_doc_details(einv_dt, dtype, dname):
    """
    Adds e-Invoice Doc details to dictionary and returns the same.
    einv_dt is the Existing Dictionary
    dtype is the Doctype in ERPNext
    dname is the Document Name in ERPNext
    """
    if len(dname) > 16:
        len_mess = f"Name of {frappe.get_desk_link(dtype, dname)} is more than 16 Characters"
        print(len_mess)
        frappe.throw(len_mess)
    doc = frappe.get_doc(dtype, dname)
    einv_dt.TranDtls = frappe._dict({})
    trans_dt = frappe._dict({})
    doc_dts = frappe._dict({})
    trans_dt.TaxSch = "GST"
    supply_type = get_einv_supply_type(gst_category=doc.gst_category, exp_type=doc.export_type)
    trans_dt.SupTyp = supply_type
    trans_dt.RegRev = get_einv_rcm(doc)
    ecom_gstin = get_ecom_gstin()
    if ecom_gstin != "":
        trans_dt.EcmGstin = ecom_gstin
    igst_on_intra = get_igst_on_intra()
    if igst_on_intra == "Y":
        trans_dt.IgstOnIntra = igst_on_intra
    einv_dt.TranDtls = trans_dt
    doc_dts.Typ = get_einv_doctype(doc)
    doc_dts.No = dname
    doc_dts.Dt = (doc.posting_date).strftime("%d/%m/%Y")
    einv_dt.DocDtls = doc_dts
    return einv_dt


def get_einv_doctype(dtd):
    """
    Returns document Type for a given ERPNext Document
    INV = Invoice, CRN = Credit Note, DBN = Debit Note
    For Sales Invoice if its return then its a credit note
    For JV if credit note or debit note based on selection
    """
    inv_type = ""
    if dtd.doctype == "Sales Invoice":
        if dtd.is_return == 1:
            inv_type = "CRN"
        else:
            inv_type = "INV"
    elif dtd.doctype == "Journal Entry":
        if dtd.voucher_type == "Credit Note":
            inv_type = "CRN"
        elif dtd.voucher_type == "Debit Note":
            inv_type = "DBN"
    if inv_type == "":
        message = f"Unable to get Invoice Type for {frappe.get_desk_link(dtd.doctype, dtd.name)}"
        print(message)
        frappe.throw(message)
    return inv_type



def get_igst_on_intra():
    """
    Returns if IGST is applicable on within State sales this is a special case need to be
    implemented as of now returns N as standard
    """
    return "N"


def get_ecom_gstin():
    """
    Returns the Ecommerce GSTIN for a given document to be Implemented
    """
    ecom_gstin = ""
    return ecom_gstin


def get_einv_rcm(doc):
    """
    Returns Y for RCM Applicable and N for RCM not applicable
    """
    rcm_type = ""
    if doc.reverse_charge == "Y":
        rcm_type = "Y"
    else:
        rcm_type = "N"
    return rcm_type


def get_einv_supply_type(gst_category, exp_type=None):
    """
    Returns text for e-Invoice Supply Type for a GST Category and Export Type
    """
    stype = ""
    if gst_category in ["Registered Regular", "Registered Composition", "UIN Holders"] :
        stype = "B2B"
    elif gst_category in ["Unregistered", "Consumer"]:
        stype = "B2C"
    elif gst_category == "Deemed Export":
        stype = "DEXP"
    elif gst_category == "Overseas":
        if exp_type == "With Payment of Tax":
            stype = "EXPWP"
        elif exp_type == "Without Payment of Tax":
            stype = "EXPWOP"
    elif gst_category == "SEZ":
        if exp_type == "With Payment of Tax":
            stype = "SEZWP"
        elif exp_type == "Without Payment of Tax":
            stype = "SEZWOP"
    if stype == "":
        message = f"Error in getting the eInvoice Supply Type \
        for GST Category:{gst_category} and Export Type: {exp_type}"
        print(message)
        frappe.throw(message)
    return stype


def einv_needed(dtype, dname):
    """
    Returns boolean is eInvoice is needed for a Document
    """
    einv_need = 0
    dtd = frappe.get_doc(dtype, dname)
    if dtype == "Sales Invoice":
        if dtd.gst_category != "Unregistered":
            einv_need = 1
    return einv_need

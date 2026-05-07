#  Copyright (c) 2022. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
import io
import re
import json
import frappe
import requests
from datetime import datetime
from pyqrcode import create as qrcreate
from frappe.utils import get_datetime, flt
from .eway_bill_api import get_eway_pass, get_taxes_type,get_taxes_type_from_doc, get_transport_mode, get_eway_distance
from .common import get_base_url, get_aspid_pass, get_default_gstin, get_numeric_state_code, \
    get_gst_pincode, get_gst_based_uom, get_place_of_supply
TIMEOUT = 10


def generate_eway_irn(dtype, dname):
    """
    Generates eWay Bill for Sales Invoice from IRN
    """
    api = "gen_eway_irn"
    full_url = get_full_einv_url(api)
    if dtype != "Sales Invoice":
        frappe.throw(f"EWay Bill is Only Possible for Sales Invoices")
    else:
        dtd = frappe.get_doc(dtype, dname)
    if not dtd.irn:
        frappe.throw(f"No IRN mentioned in {frappe.get_desk_link({dtype}, {dname})}")
    headers = get_headers()
    eway_json = json.dumps(get_eway_details(dtype, dname))
    res = requests.post(url=full_url, headers=headers, data=eway_json, timeout=TIMEOUT).json()
    # print(eway_json)
    # print(full_url)
    print(res)


def get_irn_details(irn_no):
    """
    Gets IRN details for a given IRN number
    """
    api = "get_irn"
    irn_dict = ""
    full_url = get_full_einv_url(api)
    full_url = add_qr_code_size(url=full_url)
    new_url = full_url.split("?")
    full_url = f"{new_url[0]}/{irn_no}?{new_url[1]}"
    res = requests.get(url=full_url, timeout=TIMEOUT).json()
    if flt(res.get("Status")) == 1:
        irn_dict = json.loads(res.get("Data"))
    else:
        print(res)
    return irn_dict


def generate_irn(dtype, dname):
    """
    Generates the IRN for a Document No and a Document Type
    IRN can be generated for the following documents only B2B
    1. Sales Invoice normal and credit notes based on items
    2. Journal Entry if Credit or Debit Notes for Registered Customers or Suppliers
    """
    api = "generate_irn"
    full_url = get_full_einv_url(api)
    full_url = add_qr_code_size(url=full_url)
    headers = get_headers()
    einv_json = gen_einv_json(dtype=dtype, dname=dname)
    # print(einv_json)
    res = json.loads(requests.post(url=full_url, headers=headers, data=einv_json,
        timeout=TIMEOUT).text)
    # print(res)
    if flt(res.get("Status")) == 1:
        irn_dict = json.loads(res.get("Data"))
        update_irn_details(dtype, dname, irn_dict)
    else:
        error = res.get("ErrorDetails")[0]
        if error.get("ErrorCode") == "2150":
            # Duplicate IRN so update IRN details in Invoice
            info_det = res.get("InfoDtls")[0]
            irn_dict = info_det.get("Desc")
            update_irn_details(dtype, dname, irn_dict)
            print("Updated IRN details")
        else:
            print(res)


def attach_qrcode(dtype, dname, qrcode):
    """
    Creates and Attaches the QR code from a QR Code Value
    """
    new_dname = re.sub('[^A-Za-z0-9]+', '', dname)
    filename = f"QRCode_{new_dname}.png"

    qr_image = io.BytesIO()
    url = qrcreate(qrcode, error='L')
    url.png(qr_image, scale=2, quiet_zone=1)
    file = frappe.get_doc({
            "doctype": "File",
            "file_name": filename,
            "attached_to_doctype": dtype,
            "attached_to_name": dname,
            "attached_to_field": "qrcode_image",
            "is_private": 1,
            "content": qr_image.getvalue()})
    file.save()
    frappe.db.set_value(dtype, dname, "qrcode_image", file.file_url)
    frappe.db.commit()


def update_irn_details(dtype, dname, irn_dict):
    """
    Updates the IRN No, Ack No, Ack Date in a Doctype
    """
    frappe.db.set_value(dtype, dname, "irn", irn_dict.get("Irn"))
    frappe.db.set_value(dtype, dname, "ack_no", irn_dict.get("AckNo"))
    frappe.db.set_value(dtype, dname, "ack_date", irn_dict.get("AckDt"))
    if not irn_dict.get("SignedQRCode"):
        new_irn_dict = get_irn_details(irn_dict.get("Irn"))
        qr_code = new_irn_dict.get("SignedQRCode")
    else:
        qr_code = irn_dict.get("SignedQRCode")
    attach_qrcode(dtype, dname, qr_code)


def get_headers():
    """
    Returns headers for Application
    """
    return {
        "content-type": "application/json"
    }



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
    einv_dt = add_einv_adr_details(einv_dt, buy_add, type_of_detail="buyer", pos=pos)
    einv_dt = add_einv_adr_details(einv_dt, ship_add, type_of_detail="ship",
        port_code=dtd.port_code)
    einv_it_val = get_einv_item_details(dtype, dname)
    einv_dt.ItemList = einv_it_val[0]
    einv_dt.ValDtls = einv_it_val[1]
    # einv_dt = add_eway_dict(dtype, dname, einv_dt)
    # einv_final.Data = einv_dt
    einv_json = json.dumps(einv_dt)
    # Dispatch details are only needed when there is difference in Biller and dispatcher
    # einv_dt = add_einv_adr_details(einv_dt, sell_add, type_of_detail="dispatch")
    return einv_json


def add_eway_dict(dtype, dname, exist_dict):
    """
    Adds eway details to e-Invoice dictionary if needed else throws error.
    1. Checks if the eWay Bills is needed by checking the eway bill Limit.
    2. If eway Bill needed then adds the dictionary EwbDtls to the existing dict
    """
    if dtype == "Sales Invoice":
        eway_limit = flt(frappe.get_value("Rohit Settings", "Rohit Settings", "eway_bill_limit"))
        doc_total = frappe.get_value(dtype, dname, "base_grand_total")
        if doc_total >= eway_limit:
            # Add eWay bill details
            exist_dict.EwbDtls = get_eway_details(dtype, dname)
    return exist_dict


def get_eway_details(dtype, dname):
    """
    Returns a dictionary for eway Bill for Sales Invoice and Purchase Order and for JV its not
    needed since eway is not needed
    """
    eway_dt = frappe._dict({})
    sid = frappe.get_doc(dtype, dname)
    eway_dt.Distance = get_eway_distance(frm_adr_name=sid.company_address,
        to_adr_name=sid.shipping_address_name)
    eway_dt.TransMode = str(get_transport_mode(sid.mode_of_transport))
    tpt_gstin = get_transporter_gstin(sid.transporters)
    if tpt_gstin:
        eway_dt.TransId = tpt_gstin
        eway_dt.TransDocNo = sid.lr_no
    else:
        # eway_dt.TransDocNo = sid.lr_no
        eway_dt.VehNo = sid.lr_no
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



def add_qr_code_size(url, qr_size=250):
    """
    Adds the QR Code size to the URL and returns the full URL
    """
    full_url = f"{url}&QrCodeSize={qr_size}"
    return full_url


def get_full_einv_url(api="ping_vital", gstin=None):
    """
    Returns full url for an API
    """

    aspid, asppass = get_aspid_pass()
    base_url, sbox = get_base_url()
    einv_id, einv_pass = get_eway_pass(sbox=sbox)
    if not gstin:
        gstin = get_default_gstin(sbox=sbox)
    api_details = get_einv_api(api=api)
    if sbox == 1:
        full_url = f"{base_url}"
    else:
        full_url = f"{base_url[:8]}einvapi.{base_url[8:]}"
    full_url += f"/{api_details['type']}/"
    if api_details.get("version"):
        full_url += f"{api_details['version']}/"
    full_url += f"{api_details['action']}?aspid={aspid}&password={asppass}&Gstin={gstin}"
    if api_details.get("uname") == 1:
        full_url += f"&user_name={einv_id}&eInvPwd={einv_pass}"
    if api_details.get("auth_token") == 1:
        auth_token = get_auth_token_if_needed()
        full_url += f"&AuthToken={auth_token}"
    return full_url


def get_auth_token_if_needed():
    """
    Checks the auth Token in Database and if renewal needed then renews else returns existing
    """
    rset = frappe.get_single('Rohit Settings')
    now_time = datetime.now()
    ac_token_time = get_datetime(rset.access_token_time)
    if not rset.access_token_time:
        time_diff_secs = 0
    else:
        time_diff_secs = (ac_token_time - now_time).total_seconds()
    # Check if access token is expired then generate new
    if time_diff_secs <= 0:
        res_json = get_einv_auth_token()
        if flt(res_json.get("Status")) == 1:
            data = res_json.get('Data')
            access_token = data.get("AuthToken")
            rset.access_token = access_token
            rset.access_token_time = get_datetime(data.get("TokenExpiry"))
            rset.save()
            frappe.db.commit()
            rset.reload()
        else:
            frappe.throw(f"Error while fetching the Auth Token {res_json}")
            # print(f"Error while fetching the Auth Token {res_json}")
            # exit()
            return
    else:
        access_token = rset.access_token
    return access_token


def get_einv_auth_token():
    """
    Gets the eInvoice Auth Token from the Server
    """
    api = 'auth'
    full_url = get_full_einv_url(api=api)
    response = requests.get(url=full_url, timeout=TIMEOUT)
    return response.json()


def get_einv_api(api):
    """
    Returns dictionary for API details for E-Invoices
    """

    api_details = {}
    einv_api = [
        {"api": "ping_vital", "version": "v1.04", "type": "eivital", "action": "heartbeat/ping"},
        {"api": "ping_core", "type": "eicore", "action": "heartbeat/ping"},
        {"api": "ping_eway", "type": "eiewb", "action": "heartbeat/ping"},
        {"api": "auth", "version": "dec/v1.04", "type": "eivital", "action":"auth", "uname":1},
        {"api": "generate_irn", "version": "dec/v1.03", "type": "eicore", "action": "Invoice",
        "uname":1, "auth_token":1},
        {"api": "get_irn", "version": "dec/v1.03", "type": "eicore", "action": "Invoice/irn",
        "uname":1, "auth_token":1},
        {"api": "get_irn_by_doc", "version": "dec/v1.03", "type": "eicore", "action": "Invoice/irn",
        "uname":1, "auth_token":1},
        {"api": "gen_eway_irn", "version": "dec/v1.03", "type": "eiewb", "action": "ewaybill",
        "uname":1, "auth_token":1},
        {"api": "get_eway_irn", "version": "dec/v1.03", "type": "eicore", "action": "ewaybill/irn/",
        "uname":1, "auth_token":1},
        {"api": "cancel_eway", "version": "dec/v1.03", "type": "eicore", "action": "CANEWB",
        "uname":1, "auth_token":1},
        {"api": "cancel_irn", "version": "dec/v1.03", "type": "eicore", "action": "Invoice/Cancel",
        "uname":1, "auth_token":1}
    ]
    for row in einv_api:
        if row["api"] == api:
            api_details = row
    return api_details

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


def generate_irn_from_doc(doc):
    """
    Optimized IRN generation using an already loaded document.
    Used by background jobs to avoid repeated frappe.get_doc calls.
    """

    api = "generate_irn"
    full_url = get_full_einv_url(api)
    full_url = add_qr_code_size(url=full_url)
    headers = get_headers()

    einv_json = generate_einv_json_from_doc(doc)

    try:
        response = requests.post(
            url=full_url,
            headers=headers,
            data=einv_json,
            timeout=TIMEOUT
        )
        response.raise_for_status()

    except requests.RequestException:
        frappe.log_error(
            frappe.get_traceback(),
            f"IRN API Request Failed for {doc.name}"
        )
        return

    res = json.loads(response.text)

    if flt(res.get("Status")) == 1:
        irn_dict = json.loads(res.get("Data"))
        update_irn_details(doc.doctype, doc.name, irn_dict)

    else:
        errors = res.get("ErrorDetails") or []

        if errors:
            error = errors[0]
        else:
            frappe.log_error(json.dumps(res, indent=2), "Unknown IRN Error")
            return
        if error.get("ErrorCode") == "2150":
            info_det = res.get("InfoDtls")[0]
            # CRITICAL FIX: Parse the stringified JSON
            irn_dict = json.loads(info_det.get("Desc"))
            update_irn_details(doc.doctype, doc.name, irn_dict)

        else:
            frappe.log_error(
                json.dumps(res, indent=2),
                "IRN Generation Failed"
            )


def generate_einv_json_from_doc(doc):
    """
    Generates eInvoice JSON using an already loaded document.
    """

    einv_dt = frappe._dict({})
    einv_dt.Title = "GST-India Invoice Document"
    einv_dt.Description = "GST Invoice format for IRN Generation in INDIA"
    einv_dt.Version = "1.1"

    pos = get_place_of_supply(doc.doctype, doc.name)

    einv_dt = add_einv_doc_details_from_doc(einv_dt, doc)

    sell_add = doc.company_address
    buy_add = doc.customer_address
    ship_add = doc.shipping_address_name

    einv_dt = add_einv_adr_details(einv_dt, sell_add, "seller")
    einv_dt = add_einv_adr_details(einv_dt, buy_add, "buyer", pos=pos)
    einv_dt = add_einv_adr_details(einv_dt, ship_add, "ship", port_code=doc.port_code)

    item_list, val_dt = get_einv_item_details_from_doc(doc)

    einv_dt.ItemList = item_list
    einv_dt.ValDtls = val_dt

    return json.dumps(einv_dt)


def get_einv_item_details_from_doc(doc):
    """
    Returns item details dictionary for the eInvoice JSON using a loaded document.
    """
    itm_lst = []
    val_dt = frappe._dict({})

    if doc.doctype != "Sales Invoice":
        frappe.throw(
            f"e-Invoice Not Supported for {doc.doctype} and Doc No: {doc.name}"
        )

    tax_details = get_taxes_type_from_doc(doc)

    val_dt.AssVal = round(abs(tax_details.get("tax_val", 0)), 2)
    val_dt.TotInvVal = round(abs(tax_details.get("tot_val", 0)), 2)
    val_dt.CgstVal = round(abs(tax_details.get("cgst_amt", 0)), 2)
    val_dt.SgstVal = round(abs(tax_details.get("sgst_amt", 0)), 2)
    val_dt.IgstVal = round(abs(tax_details.get("igst_amt", 0)), 2)
    val_dt.Discount = round(abs(tax_details.get("discount_amt", 0)), 2)
    val_dt.OthChrg = round(abs(tax_details.get("other_amt", 0)), 2)

    gst_rate = tax_details.get("gst_per", 0)
    igst_per = tax_details.get("igst_per", 0)
    cgst_per = tax_details.get("cgst_per", 0)
    sgst_per = tax_details.get("sgst_per", 0)

    unique_hsns = list(set(row.gst_hsn_code for row in doc.items if row.gst_hsn_code))
    
    if unique_hsns:
        hsn_records = frappe.get_all(
            "GST HSN Code",
            filters={"name": ("in", unique_hsns)},
            fields=["name", "description", "is_service"]
        )
    else:
        hsn_records = []
    
    hsn_map = {hsn.name: hsn for hsn in hsn_records}

    for row in doc.items:
        hsn_doc = hsn_map.get(row.gst_hsn_code)
        
        is_ser = "Y" if hsn_doc and flt(hsn_doc.is_service) else "N"
        prd_desc = hsn_doc.description[:299] if hsn_doc and hsn_doc.description else "Product Description Missing"

        it_row_dict = frappe._dict({})

        it_row_dict.SlNo = str(row.idx)
        it_row_dict.PrdDesc = prd_desc
        it_row_dict.IsServc = is_ser
        it_row_dict.HsnCd = row.gst_hsn_code
        it_row_dict.Qty = abs(row.qty)
        it_row_dict.Unit = get_gst_based_uom(row.uom)
        it_row_dict.UnitPrice = round(row.base_rate, 2)
        it_row_dict.TotAmt = round(abs(row.base_amount), 2)
        it_row_dict.AssAmt = round(abs(row.base_amount), 2)
        it_row_dict.GstRt = gst_rate

        it_row_dict.IgstAmt = abs(round(row.base_amount * (igst_per / 100), 2))
        it_row_dict.CgstAmt = abs(round(row.base_amount * (cgst_per / 100), 2))
        it_row_dict.SgstAmt = abs(round(row.base_amount * (sgst_per / 100), 2))

        it_row_dict.TotItemVal = abs(round(row.base_amount * (1 + gst_rate / 100), 2))

        itm_lst.append(it_row_dict)

    return itm_lst, val_dt


def add_einv_doc_details_from_doc(einv_dt, doc):
    """
    Adds document details to the eInvoice dictionary using a loaded document.
    """

    if len(doc.name) > 16:
        frappe.throw(
            f"Name of {frappe.get_desk_link(doc.doctype, doc.name)} exceeds 16 characters"
        )

    trans_dt = frappe._dict({})
    doc_dts = frappe._dict({})

    trans_dt.TaxSch = "GST"

    supply_type = get_einv_supply_type(
        gst_category=doc.gst_category,
        exp_type=doc.export_type
    )

    trans_dt.SupTyp = supply_type
    trans_dt.RegRev = get_einv_rcm(doc)

    ecom_gstin = get_ecom_gstin()
    if ecom_gstin:
        trans_dt.EcmGstin = ecom_gstin

    igst_on_intra = get_igst_on_intra()
    if igst_on_intra == "Y":
        trans_dt.IgstOnIntra = igst_on_intra

    einv_dt.TranDtls = trans_dt

    doc_dts.Typ = get_einv_doctype(doc)
    doc_dts.No = doc.name
    doc_dts.Dt = doc.posting_date.strftime("%d/%m/%Y")

    einv_dt.DocDtls = doc_dts

    return einv_dt
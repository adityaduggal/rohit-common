#  Copyright (c) 2021. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt

import re
import frappe
import requests
from datetime import datetime, timedelta
from frappe.utils import get_datetime, getdate
from frappe.utils.file_manager import save_file
from .common import get_base_url, get_aspid_pass, get_default_gstin
from ..validations.google_maps import get_distance_matrix, get_approx_dist_frm_matrix
TIMEOUT=5


def get_eway_distance(frm_adr_name, to_adr_name):
    """
    Returns distance in Integer for From and To Address based on Eway Rules
    """
    frm_doc = frappe.get_doc("Address", frm_adr_name)
    to_doc = frappe.get_doc("Address", to_adr_name)
    dist_matrix = get_distance_matrix(origin=frm_doc.pincode, dest=to_doc.pincode)
    distance = min(int(get_approx_dist_frm_matrix(dist_matrix)), 3999)

    return distance


def create_ewb_from_json(ewb_json):
    """
    Creates eway bill from JSON
    """
    action = 'GENEWAYBILL'
    res_json = process_ewb_post_request(api=api, action=action, json_data=ewb_json)
    return res_json


def cancel_ewb(ewb_no):
    action = 'CANEWB'
    res_json = process_ewb_post_request(api=api, action=action, json_data=ewb_json)


def update_partb_ewb(ewb_doc):
    action = 'VEHEWB'
    ewb_veh_data = {}
    for veh in ewb_doc.vehicles:
        ewb_veh_data['ewbNo'] = ewb_doc.eway_bill_no
        if veh.vehicle_number:
            ewb_veh_data['vehicleNo'] = veh.vehicle_number
            ewb_veh_data['transMode'] = get_transport_mode(veh.mode_of_transport)
        ewb_veh_data['fromPlace'] = veh.from_place
        ewb_veh_data['fromState'] = veh.from_state_number
        ewb_veh_data['reasonRem'] = 'First Time'
        ewb_veh_data['reasonCode'] = 4
        if veh.transport_doc_no:
            ewb_veh_data['transDocNo'] = veh.transport_doc_no
            ewb_veh_data['transDocDate'] = (getdate(veh.transport_doc_date)).strftime('%d/%m/%Y')
            ewb_veh_data['transMode'] = 4
    res_json = process_ewb_post_request(api=api, action=action, json_data=ewb_veh_data)
    ewb_doc.json_reply = str(res_json)
    return res_json


def get_eway_bill_details(ewb_no, raw_resp=0):
    api = "ewayapi"
    action = 'GetEwayBill'
    param_dt = {"param": "ewbNo", "param_val": ewb_no}
    res_json = process_ewb_get_request(api=api, action=action, param_dt=param_dt, raw_resp=raw_resp)
    return res_json


def get_ewb_by_dt_dn(dt, dn):
    action = 'GetEwayBillGeneratedByConsigner'
    parameter = 'docType'
    parm2 = 'docNo'
    dt_code = get_doctype(text=dt)
    res_json = process_ewb_get_request(api=api, action=action, parm_name=parameter, parm_val=dt_code, parm_name2=parm2,
                                       parm_val2=dn)
    return res_json


def get_ewb_date(ewb_date):
    api = "ewayapi"
    action = "GetEwayBillsByDate"
    param_dt = {"param": "date", "param_val": ewb_date}
    res_json = process_ewb_get_request(api=api, action=action, param_dt=param_dt)
    return res_json


def get_ewb_others(ewb_date):
    action = 'GetEwayBillsofOtherParty'
    parameter = 'date'
    res_json = process_ewb_get_request(api=api, action=action, parm_name=parameter, parm_val=ewb_date)
    return res_json


def get_ewb_detailed_print(ewbdoc, json_data):
    api = 'aspapi'
    action = 'printdetailewb'
    response = process_print_request(ewbdoc=ewbdoc, api=api, action=action, json=json_data,
        gstin=ewbdoc.generated_by)
    return response


def process_print_request(ewbdoc, api, action, json, gstin=None):
    """
    Process print Request and Saves the file for detailed eWay Print with eWay Doc
    """
    base_url, sbox = get_base_url()
    print_url = get_eway_url(base_url, sbox)
    aspid, asppass = get_aspid_pass()
    api_details = get_eway_api(api=api, action=action)
    if not gstin:
        gstin = get_default_gstin()
    full_url = f"{print_url}/{api}/{api_details['version']}/{action}?"
    full_url += f"aspid={aspid}&password={asppass}&Gstin={gstin}"
    response = requests.post(url=full_url, json=json, timeout=TIMEOUT)
    image_data = response.content
    save_file(f"{ewbdoc.eway_bill_no}.pdf", image_data, ewbdoc.doctype, ewbdoc.name, is_private=1)
    return response


def process_ewb_post_request(api, action, json_data):
    full_url = get_ewb_url(api, action)
    response = requests.post(url=full_url, json=json_data, timeout=TIMEOUT)
    res_json = response.json()
    ewb_no = res_json.get('ewayBillNo', "")
    if ewb_no == "":
        ewb_no = res_json.get('ewbNo', "")
    if ewb_no != "":
        if int(res_json.get('status_cd', 1)) == 1:
            return res_json
        elif int(res_json.get('status_cd')) == 0:
            frappe.msgprint('Error Returned from GST Server Check Logs')
            frappe.msgprint(str(res_json.get('error')))
    else:
        return res_json


def get_ewb_url(api, action):
    gsp_link, aspid, asppass, gstin, sandbox = get_gsp_details(api=api, action=action)
    auth_token = get_ewb_access_token()
    api_url = get_api_url(api)
    url = gsp_link + api_url + api + 'api?action=' + action + '&aspid=' + aspid + '&password=' + asppass + \
               '&gstin=' + gstin + '&authtoken=' + auth_token
    return url


def get_supply_type(data, text):
    if text == 'Outward':
        data.supplyType = 'O'
    else:
        data.supplyType = 'I'
    return data


def get_supply_sub_type(data, text):
    if text == 'Supply':
        data.subSupplyType = 1
    elif text == 'Import':
        data.subSupplyType = 2
    elif text == 'Export':
        data.subSupplyType = 3
    elif text == 'Job Work':
        data.subSupplyType = 4
    elif text == 'For Own Use':
        data.subSupplyType = 5
    elif text == 'Job work Returns':
        data.subSupplyType = 6
    elif text == 'Sales Return':
        data.subSupplyType = 7
    elif text == 'Others':
        # Here also need to mention the data.subSypplyDesc for describing supply type text(20)
        data.subSupplyType = 8
    elif text == 'SKD/CKD/Lots':
        data.subSupplyType = 9
    elif text == 'Line Sales':
        data.subSupplyType = 10
    elif text == 'Recipient Not Known':
        data.subSupplyType = 11
    elif text == 'Exhibition or Fairs':
        data.subSupplyType = 12
    return data


def get_doctype(text, data=None):
    if text == 'Tax Invoice':
        code = 'INV'
    elif text == 'Delivery Challan':
        code = 'CHL'
    elif text == 'Bill of Supply':
        code = 'BIL'
    elif text == 'Bill of Entry':
        code = 'BOE'
    elif text == 'Others':
        code = 'OTH'
    else:
        frappe.throw('Undefined Document Type {}'.format(text))
    if not data:
        return code
    else:
        data.docType = code
        return data


def get_docno(data, dt, dn):
    # Text(16) Alphanum, -, /
    doc = frappe.get_doc(dt, dn)
    if dt == 'Purchase Order':
        tax_doc = frappe.get_doc('Purchase Taxes and Charges Template', doc.taxes_and_charges)
        if tax_doc.is_import == 1:
            data.docNo = doc.boe_no
        else:
            data.docNo = doc.name
    else:
        data.docNo = doc.name
    return data


def get_from_address_doc(doc, data, text):
    if text == 'from':
        data.fromGstin = doc.from_gstin
        data.userGstin = doc.generated_by
        data.fromPincode = int(doc.from_pincode)
        data.fromStateCode = int(doc.from_state_code)
        if doc.from_state_code != 99:
            data.actFromStateCode = int(doc.from_state_code)
        else:
            data.actFromStateCode = int(doc.to_state_code)
    elif text == 'to':
        data.toGstin = doc.to_gstin
        data.toPincode = int(doc.to_pincode)
        data.toStateCode = int(doc.to_state_code)
        data.actToStateCode = int(doc.to_state_code)
    return data


def get_value_of_tax(data, doc):
    """
    Updates a frappe dictionary data with Taxable values
    """
    # data.totalValue = doc.total_value
    # data.totInvValue = doc.taxable_value
    data.totInvValue = doc.total_value
    data.totalValue = doc.taxable_value
    data.otherValue = doc.other_value
    data.cgstValue = doc.cgst_value
    data.sgstValue = doc.sgst_value
    data.igstValue = doc.igst_value
    data.cessValue = doc.cess_value
    data.cessNonAdvolValue = 0
    return data


def get_transport_mode(text):
    """
    Returns integer for Text for Transport Mode
    """
    tpt = 0
    if text == 'Road':
        tpt = 1
    elif text == 'Rail':
        tpt = 2
    elif text == 'Air':
        tpt = 3
    elif text == 'Ship':
        tpt = 4
    elif text == 'InTransit':
        tpt = 5
    else:
        frappe.throw(f"Unknow Type of Transport Mode {text}")
    return tpt


def get_transporter_id(data, dt, dn, eway_doc):
    """
    Updates Transport ID in Data Dictionary
    """
    doc = frappe.get_doc(dt, dn)
    transp_doc = frappe.get_doc('Transporters', doc.transporters)
    if transp_doc.self_pickup == 1:
        data.transporterId = eway_doc.generated_by
    else:
        if transp_doc.gstin_for_eway:
            data.transporterId = transp_doc.gstin_for_eway
        else:
            frappe.throw(f"GSTIN for {frappe.get_desk_link('Transporters', doc.transporters)} \
                is not mentioned")
    return data


def convert_int_transport_mode(mode_integer):
    """
    Converts Integer to Transport Mode and Returns Transport Mode in Text
    """
    tpt_txt = ""
    if int(mode_integer) == 1:
        tpt_txt = "Road"
    elif int(mode_integer) == 2:
        tpt_txt = "Rail"
    elif int(mode_integer) == 3:
        tpt_txt = "Air"
    elif int(mode_integer) == 4:
        tpt_txt = "Ship"
    elif int(mode_integer) == 5:
        tpt_txt = "InTransit"
    else:
        frappe.throw(f"Error: Code {mode_integer} Not in Transport List. Try Values 1 to 5")
    return tpt_txt


def get_trans_type(data, text):
    """
    Updates the frappe dictionary with transctiontype for Value
    """
    if text == 'Regular':
        data.transactionType = 1
    elif text == 'Bill To - Ship To':
        data.transactionType = 2
    elif text == 'Bill From - Dispatch From':
        data.transactionType = 3
    elif text == 'Combination of 2 and 3':
        data.transactionType = 4
    return data


def get_doc_date(data, dt, dn):
    """
    Updates the dictionary with docDate field as a string
    """
    doc = frappe.get_doc(dt, dn)
    if dt == 'Sales Invoice':
        date_string = doc.posting_date
    elif dt == 'Purchase Order':
        date_string = doc.transaction_date
    date_string = date_string.strftime('%d/%m/%Y')
    data.docDate = date_string
    return data


def get_taxes_type(dtype, dname):
    """
    Returns a dictionary with taxes amount and percentages and also returns Total GST tax
    percentage as a dictionary and would also return the taxable value
    cgst_amt = CGST Amount, cgst_per = CGST Percentage
    sgst_amt = sGST Amount, sgst_per = sGST Percentage
    igst_amt = IGST Amount, igst_per = IGST Percentage
    gst_per = Total GST Tax Percentage, tax_val = Taxable Value
    tot_val = Grand Total of the Doctype
    """
    gst_per = 0
    tax_val = 0
    taxes_dict = {}
    taxes_dict["other_amt"] = 0
    doc = frappe.get_doc(dtype, dname)
    gset = frappe.get_single('GST Settings')
    tax_val = doc.base_net_total
    for tax in doc.taxes:
        found = 0
        for acc in gset.gst_accounts:
            if tax.account_head == acc.cgst_account:
                found = 1
                taxes_dict["cgst_amt"] = tax.base_tax_amount
                taxes_dict["cgst_per"] = tax.rate
                gst_per += tax.rate
            elif tax.account_head == acc.sgst_account:
                found = 1
                taxes_dict["sgst_amt"] = tax.base_tax_amount
                taxes_dict["sgst_per"] = tax.rate
                gst_per += tax.rate
            elif tax.account_head == acc.igst_account:
                found = 1
                taxes_dict["igst_amt"] = tax.base_tax_amount
                taxes_dict["igst_per"] = tax.rate
                gst_per += tax.rate
        if found == 0:
            if re.search('discount', tax.description, re.IGNORECASE):
                taxes_dict["discount_amt"] = tax.base_tax_amount
            else:
                taxes_dict["other_amt"] += tax.base_tax_amount
    taxes_dict["gst_per"] = gst_per
    taxes_dict["tax_val"] = tax_val
    taxes_dict["tot_val"] = doc.base_grand_total
    return taxes_dict

def get_taxes_type_from_doc(doc):
    """
    Optimized version of get_taxes_type that accepts a loaded document object.
    Preserves exact matching against GST Settings and handles base_tax_amount correctly.
    """
    gst_per = 0
    taxes_dict = {
        "other_amt": 0,
        "cgst_amt": 0, "cgst_per": 0,
        "sgst_amt": 0, "sgst_per": 0,
        "igst_amt": 0, "igst_per": 0,
        "discount_amt": 0
    }
    
    gset = frappe.get_single('GST Settings')
    
    for tax in doc.taxes:
        found = 0
        for acc in gset.gst_accounts:
            if tax.account_head == acc.cgst_account:
                found = 1
                taxes_dict["cgst_amt"] = tax.base_tax_amount
                taxes_dict["cgst_per"] = tax.rate
                gst_per += tax.rate
                break
            elif tax.account_head == acc.sgst_account:
                found = 1
                taxes_dict["sgst_amt"] = tax.base_tax_amount
                taxes_dict["sgst_per"] = tax.rate
                gst_per += tax.rate
                break
            elif tax.account_head == acc.igst_account:
                found = 1
                taxes_dict["igst_amt"] = tax.base_tax_amount
                taxes_dict["igst_per"] = tax.rate
                gst_per += tax.rate
                break
                
        if found == 0:
            if tax.description and re.search('discount', tax.description, re.IGNORECASE):
                taxes_dict["discount_amt"] = tax.base_tax_amount
            else:
                taxes_dict["other_amt"] += tax.base_tax_amount
                
    taxes_dict["gst_per"] = gst_per
    taxes_dict["tax_val"] = doc.base_net_total
    taxes_dict["tot_val"] = doc.base_grand_total
    
    return taxes_dict

def get_items_table(data, tbl_dict):
    """
    Updates the data dictionary with CGST, SGST and IGST rates and Item Code and Description
    """
    it_dict = {}
    for row in tbl_dict:
        uom_doc = frappe.get_doc('UOM', row.uom)
        tariff_doc = frappe.get_doc('Customs Tariff Number', row.gst_hsn_code)
        it_dict['itemNo'] = row.idx
        # it_dict['productId'] = row.item_code
        it_dict['productName'] = tariff_doc.item_code
        it_dict['productDesc'] = tariff_doc.description
        it_dict['hsnCode'] = row.gst_hsn_code
        it_dict['quantity'] = row.qty
        if uom_doc.eway_bill_uom:
            it_dict['qtyUnit'] = uom_doc.eway_bill_uom
        else:
            frappe.throw(f"No UOM Mapping Defined for {frappe.get_desk_link('UOM', row.uom)}")
        it_dict['cgstRate'] = row.cgst_rate
        it_dict['sgstRate'] = row.sgst_rate
        it_dict['igstRate'] = row.igst_rate
        it_dict['cessRate'] = row.cess_rate
    data.itemList = [it_dict]
    return data


def search_existing_ewb(ewb_no):
    """
    Searchs for Existing Eway Bill in DB based on Eway Bill No
    """
    exist_ewb = frappe.db.sql("""SELECT name FROM `tabeWay Bill` WHERE eway_bill_no = '%s'
    AND docstatus != 2""" %(ewb_no), as_dict=1)
    return exist_ewb


def ewb_from_ewb_summary(ewbj):
    """
    Creates a eWay Bill Doc for eWay Bill Summary
    """
    existing_ewb = search_existing_ewb(ewbj.get('ewbNo'))
    if not existing_ewb:
        ewb = frappe.new_doc('eWay Bill')
        update = 0
    else:
        ewb = frappe.get_doc('eWay Bill', existing_ewb[0].name)
        update = 1
    ewb.eway_bill_no = ewbj.get('ewbNo')
    ewb.eway_bill_date = datetime.strptime(ewbj.get('ewbDate'), '%d/%m/%Y %I:%M:%S %p')
    ewb.status = ewbj.get('status')
    ewb.generated_by = ewbj.get('genGstin')
    # Search for Doc Number in Global Search if Found Then Update the Document Type as well.
    ewb.ewb_doc_no = ewbj.get('docNo')
    ewb.document_date = datetime.strptime(ewbj.get('docDate'), '%d/%m/%Y')
    ewb.to_pincode = ewbj.get('delPinCode')
    ewb.to_state_code = ewbj.get('delStateCode')
    ewb.to_place = ewbj.get('delPlace')
    if ewbj.get('validUpto') != '':
        ewb.valid_upto = datetime.strptime(ewbj.get('validUpto'), '%d/%m/%Y %I:%M:%S %p')
    ewb.extended_times = ewbj.get('extendedTimes')
    ewb.reject_status = ewbj.get('rejectStatus')
    ewb.save()
    if update == 0:
        text = 'Created'
    else:
        text = 'Updated'
    frappe.msgprint(f"{text} {frappe.get_desk_link('eWay Bill', ewb.name)} with eWay Bill# \
        {ewb.eway_bill_no}")


def ewb_from_ewb_detail(ewbj):
    """
    Create Eway Bill from Eway Bill Details
    """
    frappe.msgprint(str(ewbj))
    gstin = frappe.get_value('Rohit Settings', 'Rohit Settings', 'gstin')
    # First Search for eWay Bill if not exists then create a new eWay Bill
    existing_ewb = search_existing_ewb(ewbj.get('ewbNo'))
    if not existing_ewb:
        ewb = frappe.new_doc('eWay Bill')
        update = 0
    else:
        ewb = frappe.get_doc('eWay Bill', existing_ewb[0].name)
        update = 1
    ewb.eway_bill_no = ewbj.get('ewbNo')
    ewb.eway_bill_date = datetime.strptime(ewbj.get('ewayBillDate'), '%d/%m/%Y %I:%M:%S %p')
    ewb.generation_mode = ewbj.get('genMode')
    ewb.status = ewbj.get('status')
    ewb.generated_by = ewbj.get('userGstin')
    if ewb.generated_by == gstin:
        ewb.supply_type = 'Outward'
    else:
        ewb.supply_type = 'Inward'
    # Search for Doc Number in Global Search if Found Then Update the Document Type as well.
    ewb.ewb_doc_no = ewbj.get('docNo')
    ewb.document_date = datetime.strptime(ewbj.get('docDate'), '%d/%m/%Y')
    ewb.from_trade_name = ewbj.get('fromTrdName')
    ewb.from_gstin = ewbj.get('fromGstin')
    ewb.from_pincode = ewbj.get('fromPincode')
    ewb.from_state_code = ewbj.get('fromStateCode')
    ewb.from_address_text = ewbj.get('fromAddr1') + "," + ewbj.get('fromAddr2') + '\n' + ewbj.get('fromPlace') + \
                            ", " + "State Code: " + str(ewbj.get('fromStateCode')) + ", " + \
                            str(ewbj.get('fromPincode'))
    ewb.to_trade_name = ewbj.get('toTrdName')
    ewb.to_gstin = ewbj.get('toGstin')
    ewb.to_pincode = ewbj.get('toPincode')
    ewb.to_state_code = ewbj.get('toStateCode')
    ewb.to_place = ewbj.get('toPlace')
    ewb.to_address_text = ewbj.get('toAddr1') + "," + ewbj.get('toAddr2') + '\n' + ewbj.get('toPlace') + ", " \
                                "" + "State Code: " + str(ewbj.get('toStateCode')) + ", " + str(ewbj.get(
                                    'toPincode'))
    if ewbj.get('validUpto') != '':
        ewb.valid_upto = datetime.strptime(ewbj.get('validUpto'), '%d/%m/%Y %I:%M:%S %p')
    ewb.extended_times = ewbj.get('extendedTimes')
    ewb.reject_status = ewbj.get('rejectStatus')
    ewb.taxable_value = ewbj.get('totalValue')
    ewb.total_value = ewbj.get('totInvValue')
    ewb.sgst_value = ewbj.get('sgstValue')
    ewb.cgst_value = ewbj.get('cgstValue')
    ewb.igst_value = ewbj.get('igstValue')
    ewb.cess_value = ewbj.get('cessValue')
    ewb.approx_distance = ewbj.get('actualDist')
    ewb.items = []
    if ewbj.get('itemList'):
        it_dict = {}
        for item in ewbj.get('itemList'):
            it_dict["idx"] = item.get('itemNo')
            it_dict["product_id"] = item.get('productId')
            it_dict["item_code"] = item.get('productName')
            it_dict["description"] = item.get('productDesc')
            it_dict["gst_hsn_code"] = item.get('hsnCode')
            it_dict["qty"] = item.get('quantity')
            it_dict["uom"] = item.get('qtyUnit')
            it_dict["cgst_rate"] = item.get('cgstRate')
            it_dict["sgst_rate"] = item.get('sgstRate')
            it_dict["igst_rate"] = item.get('igstRate')
            it_dict["cess_rate"] = item.get('cessRate')
            it_dict["cess_non_advol"] = item.get('cessNonAdvol')
            it_dict["base_amount"] = item.get('taxableAmount')
        ewb.append("items", it_dict.copy())
    ewb.vehicles=[]
    if ewbj.get('VehiclListDetails'):
        veh_dict={}
        for veh in ewbj.get('VehiclListDetails'):
            veh_dict["update_mode"] = veh.get('updMode')
            veh_dict["vehicle_number"] = veh.get('vehicleNo')
            veh_dict["from_place"] = veh.get('fromPlace')
            veh_dict["from_state_number"] = veh.get('fromState')
            veh_dict["mode_of_transport"] = convert_int_transport_mode(veh.get('transMode'))
            veh_dict["transport_doc_no"] = veh.get('transDocNo')
            veh_dict["transport_doc_date"] = datetime.strptime(veh.get('transDocDate'), '%d/%m/%Y')
            ewb.append("vehicles", veh_dict.copy())
    ewb.save()
    ewb.reload()
    ewb.submit()
    if update == 0:
        text = 'Created'
    else:
        text = 'Updated'
    frappe.msgprint(f"{text} {frappe.get_desk_link('eWay Bill', ewb.name)} with eWay Bill# \
        {ewb.eway_bill_no}")


def others_ewb_from_summary(ewbj):
    existing_ewb = search_existing_ewb(ewbj.get('ewbNo'))
    if not existing_ewb:
        ewb = frappe.new_doc('eWay Bill')
        update = 0
    else:
        ewb = frappe.get_doc('eWay Bill', existing_ewb[0].name)
        update = 1
    ewb.eway_bill_no = ewbj.get('ewbNo')
    ewb.eway_bill_date = datetime.strptime(ewbj.get('ewayBillDate'), '%d/%m/%Y %I:%M:%S %p')
    ewb.status = ewbj.get('status')
    ewb.generated_by = ewbj.get('genGstin')
    # Search for Doc Number in Global Search if Found Then Update the Document Type as well.
    ewb.ewb_doc_no = ewbj.get('docNo')
    ewb.document_date = datetime.strptime(ewbj.get('docDate'), '%d/%m/%Y')
    ewb.reject_status = ewbj.get('rejectStatus')
    ewb.save()
    if update == 0:
        text = 'Created'
    else:
        text = 'Updated'
    frappe.msgprint(f"{text} {frappe.get_desk_link('eWay Bill', ewb.name)} with eWay Bill# \
        {ewb.eway_bill_no}")


def get_ewb_access_token():
    """
    Checks the auth token in DB if expired or is going to expire in 10 mins or 600 secs
    then calls and gets the Auth token refreshed from Server
    """
    rset = frappe.get_single('Rohit Settings')
    now_time = datetime.now()
    ac_token_time = get_datetime(rset.access_token_time)
    if not rset.access_token_time:
        time_diff_secs = 0
    else:
        time_diff_secs = (ac_token_time - now_time).total_seconds()
    # Only Need Access Token after 6 hours of getting the first one since Access Token is Valid
    # for 6 hours once taken from server and call only when its expired
    if time_diff_secs <= 0:
        res_json = get_eway_auth_token()
        if res_json.get("status") == '1':
            access_token = res_json.get("authtoken")
            rset.access_token = access_token
            rset.access_token_time = now_time + timedelta(hours=6)
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


def get_eway_auth_token():
    """
    Gets the eWay Bill Auth Token from the Server
    """
    api = 'auth'
    full_url = get_full_eway_url(api=api)
    response = requests.get(url=full_url, timeout=TIMEOUT)
    print(response.json())
    return response.json()


def process_ewb_get_request(api, action=None, param_dt=None, raw_resp=0):
    """
    Returns the Eway Response based on API and Param Dict
    """
    full_url = get_full_eway_url(api=api, action=action, param_dt=param_dt)
    response = requests.get(url=full_url, timeout=TIMEOUT)
    if raw_resp == 1:
        res_json = response
    else:
        res_json = response.json()
    return res_json


def get_full_eway_url(api="auth", action=None, gstin=None, param_dt=None):
    """
    Returns full eWay bill related URL based on the API being used
    """
    aspid, asppass = get_aspid_pass()
    eway_uname, eway_pass = get_eway_pass()
    base_url, sbox = get_base_url()
    api_details = get_eway_api(api, action=action)
    if not gstin:
        gstin = get_default_gstin()

    full_url = get_eway_url(base_url, sbox)
    if api_details.get("version"):
        full_url += f"/{api_details['version']}/dec"
    full_url += f"/{api}?action={api_details['action']}&aspid={aspid}&password={asppass}"
    full_url += f"&gstin={gstin}&username={eway_uname}&ewbpwd={eway_pass}"

    if api_details.get("token", 0) == 1:
        auth_token = get_ewb_access_token()
        full_url += f"&authtoken={auth_token}"

    if param_dt:
        if param_dt.get("param", None):
            full_url += f"&{param_dt['param']}={param_dt['param_val']}"
        if param_dt.get("param2", None):
            full_url += f"&{param_dt['param2']}={param_dt['param_val2']}"
    print(full_url)
    return full_url


def get_eway_url(base_url, sbox):
    """
    Returns the URL based on Sandbox or not
    """
    if sbox == 1:
        full_url = f"{base_url}"
    else:
        full_url = f"{base_url[:8]}einvapi.{base_url[8:]}"
    return full_url


def get_eway_pass(sbox=0):
    """
    Returns the E-Invoices user ID and password
    """
    rset = frappe.get_doc("Rohit Settings", "Rohit Settings")
    if sbox == 0:
        eway_id = rset.eway_bill_id
        eway_pass = rset.eway_bill_password
    else:
        eway_id = "rohit_sand_taxpro"
        eway_pass = "ASJ9Ar3@@C"

    return eway_id, eway_pass


def get_eway_api(api, action=None):
    """
    Returns dictionary for API details for Eway Bills
    """
    api_details = {}
    eway_api = [
        {"api": "auth", "version": "v1.03", "action":"ACCESSTOKEN"},
        {"api": "ewayapi", "version": "v1.03", "action":"GetEwayBillsByDate", "token": 1},
        {"api": "ewayapi", "version": "v1.03", "action":"GetEwayBill", "token": 1},
        {"api": "aspapi", "version": "v1.0", "action":"printdetailewb"}
    ]
    for row in eway_api:
        if row["api"] == api:
            if action:
                if row["action"] == action:
                    api_details = row
            else:
                api_details = row
    return api_details

#  Copyright (c) 2022. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-

from __future__ import unicode_literals
import re
import frappe
from datetime import date
from frappe.utils import getdate, flt
from frappe.utils.background_jobs import enqueue
from ...utils.rohit_common_utils import replace_java_chars, check_dynamic_link, \
    check_sales_taxes_integrity, remove_html

def on_submit(doc, method):
    if len(doc.items) >= 10:
        frappe.msgprint(f"{doc.name} has more than 10 items hence submission is Queued Check back later after 10 mins.")
        doc.queue_action("submit", queue="long", timeout=600)


def validate(doc, method):
    # ttd = Tax Template Document
    ttd = frappe.get_doc("Sales Taxes and Charges Template", doc.taxes_and_charges)
    check_all_dynamic_links(doc)
    check_local_natl_tax_rules(doc, ttd)
    update_sender_details(doc, ttd)
    check_series(doc, ttd)
    validate_address_google_update(doc)
    check_delivery_note_rule(doc)
    check_govt_related_rules(doc)
    check_sales_taxes_integrity(doc)
    add_list = [doc.customer_address, doc.shipping_address_name]
    for add in add_list:
        check_validated_gstin(add, doc)


def check_govt_related_rules(doc):
    """
    Checks for Various Govt Related Rules and updates GST related rules and fields
    """
    check_customs_tariff(doc)
    update_gst_related_fields(doc)
    validate_other_fields(doc)


def update_gst_related_fields(si_doc):
    """
    Updates the fields for Sales Invoice Doc, the following fields are updated
    1. GST Category which determines type of Supply like B2B, B2C, Export (with or without Payment)
    or SEZ (with or without Payment) or Deemed Export
    """
    if si_doc.background_processing == 1:
        si_doc.marked_to_submit = 0
    tax_adr = frappe.get_value("Accounts Settings", "Accounts Settings",
        "determine_address_tax_category_from")
    if tax_adr == "Billing Address":
        adr_fd = "customer_address"
    else:
        adr_fd = "shipping_address_name"
    comp_ctry = frappe.get_value("Address", si_doc.company_address, "country")
    gst_active = frappe.get_value("Country", comp_ctry, "gst_details")
    adr_doc = frappe.get_doc("Address", si_doc.get(adr_fd))
    if gst_active == 1:
        # Reverse Charge is Set to Statically No
        si_doc.reverse_charge = "N"
        if adr_doc.country == comp_ctry:
            if adr_doc.gstin == "NA":
                si_doc.gst_category = "Unregistered"
            else:
                si_doc.gst_category = "Registered Regular"
        else:
            si_doc.gst_category = "Overseas"


def check_all_dynamic_links(doc):
    check_dynamic_link(parenttype="Address", parent=doc.customer_address, link_doctype="Customer",
                       link_name=doc.customer)
    check_dynamic_link(parenttype="Address", parent=doc.shipping_address_name,
                       link_doctype="Customer", link_name=doc.customer)
    check_dynamic_link(parenttype="Contact", parent=doc.contact_person, link_doctype="Customer", link_name=doc.customer)


def check_series(doc, tx_doc):
    series_regex = replace_java_chars(tx_doc.series)
    if series_regex:
        if 'or' in series_regex:
            ser_regex = series_regex.split("or")
        else:
            ser_regex = [series_regex]
        series_regex_pass = 0
        for d in ser_regex:
            p = re.compile(d.strip())
            if not p.match(doc.name):
                pass
            else:
                series_regex_pass = 1
        if series_regex_pass != 1:
            frappe.throw("{}: is not as per the defined Series in {}".
                         format(doc.name, tx_doc.name))
    else:
        frappe.throw("Series Regex Not Defined for {} and {}".
                     format(frappe.get_desk_link(doc.doctype, doc.name),
                            frappe.get_desk_link(tx_doc.doctype, tx_doc.name)))


def on_update(doc, method):
    validate_export_bill_fields(doc)
    check_govt_related_rules(doc)
    it_list, needs_update = get_item_synopsis(doc)
    if needs_update == 1:
        doc.items_synopsis = []
        for d in it_list:
            doc.append("items_synopsis", d.copy())


def update_sender_details(doc, tmp_doc):
    if tmp_doc.from_address:
        send_add_doc = frappe.get_doc('Address', tmp_doc.from_address)
        doc.company_address = tmp_doc.from_address
        doc.company_gstin = send_add_doc.gstin
    else:
        frappe.throw("From Address is Needed in {}".format(frappe.get_desk_link(tmp_doc.doctype, tmp_doc.name)))


def check_local_natl_tax_rules(doc, template_doc):
    """
    Checks rules of GST Tax as per States and also updates the fields in the document
    """
    # Will only check if the Tax Rate is not Sample
    # Check if Shipping State is Same as Template State then check if the tax template is LOCAL
    # Else if the States are different then the template should NOT BE LOCAL
    bill_state = frappe.db.get_value("Address", doc.customer_address, "state_rigpl")
    ship_country = frappe.db.get_value("Address", doc.shipping_address_name, "country")

    if bill_state == template_doc.state and template_doc.is_export == 0 and \
            template_doc.is_sample != 1:
        # doc.place_of_supply = template_doc.state
        if template_doc.is_local_sales != 1:
            frappe.throw(f"Selected Tax {doc.taxes_and_charges} is NOT LOCAL Tax but Billing \
                Address is in Same State {bill_state}, hence either change Billing Address or \
                Change the Selected Tax")
    elif ship_country == 'India' and bill_state != template_doc.state and \
            template_doc.is_sample != 1:
        # doc.place_of_supply = bill_state
        if template_doc.is_local_sales == 1:
            frappe.throw(f"Selected Tax {doc.taxes_and_charges} is LOCAL Tax but Billing Address \
                is in Different State {bill_state}, hence either change Billing Address or Change \
                the Selected Tax")
    elif ship_country != 'India':  # Case of EXPORTS
        # doc.place_of_supply = "Exempted"
        if template_doc.is_export != 1:
            frappe.throw(f"Selected Tax {doc.taxes_and_charges} is for Indian Sales but Billing \
                Address is in Different Country {ship_country}, hence either change Billing \
                Address or Change the Selected Tax")


def check_customs_tariff(doc):
    """
    Removes HTML tags and also does not allow CTSH below 6 digit or any item which is not linked
    to a Customs Tariff
    """
    for items in doc.items:
        items.description = remove_html(items.description)
        custom_tariff = frappe.db.get_value("Item", items.item_code, "customs_tariff_number")
        if custom_tariff:
            if len(custom_tariff) >= 6:
                items.gst_hsn_code = custom_tariff
            else:
                frappe.throw(f"Item Code {items.item_code} in line# {items.idx} has a Custom \
                    Tariff {custom_tariff} which is less than 6 digit, please get the Custom \
                    Tariff corrected")
        else:
            frappe.throw(f"Item Code {items.item_code} in line# {items.idx} does not have linked \
                Customs Tariff in Item Master")


def validate_other_fields(doc):
    validate_add_fields(doc)
    validate_export_bill_fields(doc)
    it_list, needs_update = get_item_synopsis(doc)
    if needs_update == 1:
        doc.items_synopsis = []
        for d in it_list:
            doc.append("items_synopsis", d.copy())


def get_item_synopsis(doc):
    """
    Returns Item List for Synopsis and also integer if item synopsis needs to be Updated
    """
    it_list = []
    needs_update = 0
    syn_net_total = 0
    syn_tot_qty = 0
    for row in doc.items_synopsis:
        syn_net_total += row.base_amount
        syn_tot_qty += row.qty
    if round(syn_net_total, 1) != round(doc.base_net_total, 1) or syn_tot_qty != doc.total_qty:
        needs_update = 1
    for item in doc.items:
        if item.idx == 1:
            it_list = update_item_table(it_list, item)
        else:
            found = 0
            for d in it_list:
                if found == 0:
                    if d.gst_hsn_code == item.gst_hsn_code and d.stock_uom == item.stock_uom:
                        d["qty"] = d["qty"] + item.qty
                        d["amount"] = d["amount"] + item.amount
                        d["base_amount"] = round(d["base_amount"] + item.base_amount, 2)
                        d["rate"] = round(d["amount"] / d["qty"], 2)
                        d["base_rate"] = round(d["base_amount"] / d["qty"], 2)
                        found = 1
                        break
            if found == 0:
                it_list = update_item_table(it_list, item)
    return it_list, needs_update


def check_delivery_note_rule(doc):
    dn_dict = frappe._dict()
    list_of_dn_dict = []

    for d in doc.items:
        # Stock Items without DN would need Update Stock Check
        if d.delivery_note is None:
            item_doc = frappe.get_doc('Item', d.item_code)
            if item_doc.is_stock_item == 1 and doc.update_stock != 1:
                frappe.throw(("Item Code {0} in Row # {1} is Stock Item without any DN so please check "
                              "Update Stock Button").format(d.item_code, d.idx))

        if d.dn_detail not in list_of_dn_dict and d.delivery_note is not None:
            dn_dict['dn'] = d.delivery_note
            dn_dict['dn_detail'] = d.dn_detail
            dn_dict['item_code'] = d.item_code
            list_of_dn_dict.append(dn_dict.copy())
        # With SO DN is mandatory
        if d.sales_order is not None and d.delivery_note is None:
            # Rule no.5 in the above description for disallow SO=>SI no skipping DN
            frappe.throw(("""Error in Row# {0} has SO# {1} but there is no DN.
            Hence making of Invoice is DENIED""").format(d.idx, d.sales_order))
        # With DN SO is mandatory
        if d.delivery_note is not None and d.sales_order is None:
            frappe.throw(("""Error in Row# {0} has DN# {1} but there is no SO.
            Hence making of Invoice is DENIED""").format(d.idx, d.delivery_note))
        # For DN items quantities should be same
        if d.delivery_note is not None:
            dn_qty = frappe.db.get_value('Delivery Note Item', d.dn_detail, 'qty')
            if dn_qty != d.qty:
                frappe.throw("Invoice Qty should be equal to DN quantity of {0} at Row # {1}".format(dn_qty, d.idx))
    if list_of_dn_dict:
        unique_dn = {v['dn']: v for v in list_of_dn_dict}.values()
        for dn in unique_dn:
            dn_doc = frappe.get_doc('Delivery Note', dn.dn)
            for d in dn_doc.items:
                if not any(x['dn_detail'] == d.name for x in list_of_dn_dict):
                    frappe.throw(("Item No: {0} with Item Code: {1} in DN# {2} is not mentioned in "
                                  "SI# {3}").format(d.idx, d.item_code, dn_doc.name, doc.name))


def update_item_table(it_list, item_row):
    it_dict = frappe._dict({})
    tariff_doc = frappe.get_doc('Customs Tariff Number', item_row.gst_hsn_code)
    it_dict["item_code"] = tariff_doc.item_code
    it_dict["description"] = tariff_doc.description
    it_dict["qty"] = item_row.qty
    it_dict["uom"] = item_row.uom
    it_dict["conversion_factor"] = item_row.conversion_factor
    it_dict["gst_hsn_code"] = item_row.gst_hsn_code
    it_dict["stock_uom"] = item_row.stock_uom
    it_dict["amount"] = item_row.amount
    it_dict["base_amount"] = round(item_row.base_amount, 2)
    it_dict["base_rate"] = round(it_dict["base_amount"] / it_dict["qty"], 2)
    it_dict["rate"] = round(it_dict["amount"] / it_dict["qty"], 2)
    it_dict["income_account"] = item_row.get('income_account', '')
    it_dict["cost_center"] = item_row.cost_center
    it_dict["expense_account"] = item_row.expense_account
    it_list.append(it_dict.copy())
    return it_list


def validate_export_bill_fields(doc):
    trans_doc = frappe.get_doc("Transporters", doc.transporters)
    tx_tmp_doc = frappe.get_doc('Sales Taxes and Charges Template', doc.taxes_and_charges)
    ship_add_doc = frappe.get_doc('Address', doc.shipping_address_name)
    if tx_tmp_doc.is_export == 1 and tx_tmp_doc.is_sample != 1:
        if not ship_add_doc.airport and doc.mode_of_transport == 'Air':
            frappe.throw('Airport is Needed for {} in {}'.
                         format(frappe.get_desk_link('Address', doc.shipping_address_name),
                                frappe.get_desk_link(doc.doctype, doc.name)))
        if not ship_add_doc.sea_port and doc.mode_of_transport == 'Ship':
            frappe.throw('Sea Port is Needed for {} in {}'.
                         format(frappe.get_desk_link('Address', doc.shipping_address_name),
                                frappe.get_desk_link(doc.doctype, doc.name)))
        if doc.mode_of_transport not in ('Air', 'Ship'):
            frappe.throw('Only Air or Sea as Mode of Transport is Allowed for Export Related {}'.
                         format(frappe.get_desk_link(doc.doctype, doc.name)))
        if not tx_tmp_doc.iec_code:
            frappe.throw('IEC Code is not Mentioned in {} for {}'.
                         format(frappe.get_desk_link('Sales Taxes and Charges Template', doc.taxes_and_charges),
                                frappe.get_desk_link(doc.doctype, doc.name)))
        if not tx_tmp_doc.bank_ad_code:
            frappe.throw('Bank AD Code is not Mentioned in {} for {}'.format(
                frappe.get_desk_link('Sales Taxes and Charges Template', doc.taxes_and_charges),
                frappe.get_desk_link(doc.doctype, doc.name)))
        if not tx_tmp_doc.bank_ifsc_code:
            frappe.throw('Bank IFSC Code is not Mentioned in {} for {}'.
                         format(frappe.get_desk_link('Sales Taxes and Charges Template', doc.taxes_and_charges),
                                frappe.get_desk_link(doc.doctype, doc.name)))
        if not tx_tmp_doc.export_type:
            frappe.throw('Export Type is not Mentioned in {} for {}'.
                         format(frappe.get_desk_link('Sales Taxes and Charges Template', doc.taxes_and_charges),
                                frappe.get_desk_link(doc.doctype, doc.name)))
        elif tx_tmp_doc.export_type == "Without Payment of Tax":
            if not tx_tmp_doc.lut_no_and_date:
                frappe.throw("{} is Without Payment of Taxes hence LUT is Mandatory".
                             format(frappe.get_desk_link(tx_tmp_doc.doctype, tx_tmp_doc.name)))
        if not trans_doc.port_code:
            frappe.throw("{} does not have Port Code Mentioned".
                         format(frappe.get_desk_link(trans_doc.doctype, trans_doc.name)))
        else:
            doc.port_code = trans_doc.port_code[:6]
        if not doc.payment_terms_template:
            frappe.throw("For Export {} Payment Terms Template is Mandatory".
                         format(frappe.get_desk_link(doc.doctype, doc.name)))
        else:
            ptt = frappe.get_doc("Payment Terms Template", doc.payment_terms_template)
            if not ptt.description:
                frappe.throw("For Export {} Payment Terms Template Description is Mandatory for {}".
                         format(frappe.get_desk_link(doc.doctype, doc.name),
                                frappe.get_desk_link(ptt.doctype, ptt.name)))
        doc.export_type = tx_tmp_doc.export_type


def validate_add_fields(doc):
    ship_pincode = frappe.db.get_value("Address", doc.shipping_address_name, "pincode")
    bill_pincode = frappe.db.get_value("Address", doc.customer_address, "pincode")
    ship_gstin = frappe.db.get_value("Address", doc.shipping_address_name, "gstin")
    bill_gstin = frappe.db.get_value("Address", doc.customer_address, "gstin")

    if ship_pincode is None:
        frappe.throw("Shipping Pincode is Mandatory or NA, please correct it in Shipping Address {0}".
                     format(frappe.get_desk_link('Address', doc.shipping_address_name)))

    if bill_pincode is None:
        frappe.throw("Billing Pincode is Mandatory or NA, please correct it in Billing Address {0}".
                     format(frappe.get_desk_link('Address', doc.shipping_address_name)))

    doc.shipping_address_gstin = ship_gstin
    doc.billing_address_gstin = bill_gstin


def validate_address_google_update(doc):
    bill_to_add_doc = frappe.get_doc('Address', doc.customer_address)
    ship_to_add_doc = frappe.get_doc('Address', doc.shipping_address_name)
    validate_address(bill_to_add_doc)
    validate_address(ship_to_add_doc)


def validate_address(add_doc):
    if not add_doc.json_reply and add_doc.dont_update_from_google != 1:
        frappe.throw(
            'Address {} is Not Updated from Google, Please Open and Save the Address once'.format(add_doc.name))


def check_validated_gstin(add_name, doc=None):
    # If the Validation Date for GSTIN Validation is more than 90 days then Don't allow and aks for Revalidation
    stale_days = flt(frappe.get_value("Rohit Settings", "Rohit Settings", "stale_gstin_validation_days"))
    add_doc = frappe.get_doc("Address", add_name)
    status = ""
    if add_doc.gstin:
        if add_doc.gstin != "NA":
            if add_doc.gst_validation_date:
                days_since_validation = (date.today() - getdate(add_doc.gst_validation_date)).days
            else:
                days_since_validation = 999
            # if add_doc.validated_gstin != add_doc.gstin or days_since_validation > stale_days:
            #     frappe.throw(f"GSTIN# {add_doc.gstin} for {frappe.get_desk_link(add_doc.doctype, add_doc.name)} is "
            #                  f"NOT Validated from GST Website. Please update the Address from GST Website")
            if add_doc.gst_status == "Suspended":
                if doc:
                    if doc.doctype == "Sales Invoice":
                        if doc.base_grand_total >= 50000:
                            frappe.throw(f"For {frappe.get_desk_link('Address', add_name)} GSTIN:{add_doc.gstin} is "
                                         f"{add_doc.gst_status} hence Grand Total Cannot be more than 50000")
                        else:
                            if doc.outstanding_amount > 0:
                                frappe.throw(f"For {doc.name} the GSTIN:{add_doc.gstin} is {add_doc.gst_status}. Hence "
                                             f"Outstanding Amount Cannot be Greater than 0")
                    elif doc.doctype in ("Purchase Invoice", "Purchase Receipt", "Purchase Order"):
                        frappe.throw(f"For {frappe.get_desk_link('Address', add_name)}, GSTIN: {add_doc.gstin} is "
                                     f"{add_doc.gst_status} hence {doc.doctype} is Not Allowed")
                    else:
                        frappe.msgprint(f"For {frappe.get_desk_link('Address', add_name)}, GSTIN: {add_doc.gstin} is "
                                        f"{add_doc.gst_status} hence {doc.name} being made can get Stuck Later")
            elif add_doc.gst_status in ("Cancelled", "Inactive"):
                add_doc.disabled = 1
                if doc:
                    frappe.throw(f"For {frappe.get_desk_link('Address', add_name)} GSTIN: {add_doc.gstin} is "
                                 f"{add_doc.gst_status} hence Not Allowed to Make {doc.doctype}")

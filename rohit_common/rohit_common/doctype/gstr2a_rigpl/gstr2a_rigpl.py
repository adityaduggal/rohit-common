# Copyright (c) 2021, Rohit Industries Ltd. and contributors
# For license information, please see license.txt
# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import frappe
import json
from datetime import datetime
from frappe.utils import flt, getdate
from ...india_gst_api.common import gst_return_period_validation, validate_gstin
from ...india_gst_api.gst_api import get_invoice_type, get_type_of_amend, get_gstr2a, get_gstr2b
from frappe.model.document import Document

gstr2b_actions = [{"action": "GET2B", "name": "GSTR2B"}]
gstr2a_actions = [{"action": "B2B", "name": "B2B"}, {"action": "B2BA", "name": "B2B Amendments"},
                  {"action": "CDN", "name": "Credit or Debit Notes"},
                  {"action": "CDNA", "name": "Credit or Debit Note Amendments"},
                  {"action": "IMPG", "name": "Import Data"}, {"action": "IMPGSEZ", "name": "Imports from SEZ"},
                  {"action": "ISD", "name": "Input Service Distributer"},
                  {"action": "TCS", "name": "Tax Collected at Source"},
                  {"action": "TDS", "name": "Tax Deducted at Source"}]
"""
gstr2a_actions = [{"action": "TCS", "name": "Tax Collected at Source"}]
"""


class GSTR2ARIGPL(Document):

    def reset_matching(self):
        for d in self.invoices:
            d.fully_matched = 0
        self.analyse_data(dont_save=1)

    def validate(self):
        # Month and Year cannot be equal or greater than current month. Also only 1 GSTR2A for GSTIN and Period
        gst_return_period_validation(self.return_period)
        validate_gstin(self.gstin)
        if self.invoices:
            self.analyse_data(dont_save=1)

    def on_submit(self):
        frappe.throw("Submission is Disabled for Now")

    def clear_table(self):
        self.invoices = []
        self.gstr2b_gen_date = ""
        self.filed_taxable_value = 0
        self.filed_tax_amount = 0
        self.matched_taxable_value = 0
        self.total_taxable_value = 0
        self.unfiled_tax_amount = 0
        self.unfiled_taxable_value = 0
        self.unmatched_taxable_value = 0

    def get_gstr2a_data(self):
        if self.is_new() == 1:
            frappe.throw("Save the document before Getting GSTR2A Data")
        if self.disable_gst_update == 1:
            frappe.throw("GST Network Update is Disabled. Uncheck Disable GST Update to update from GST. Also note"
                         "Updating from GST Network would remove all manual remarks and linking")
        self.flags.ignore_permissions = True
        self.clear_table()
        for action in gstr2a_actions:
            resp = get_gstr2a(gstin=self.gstin, ret_period=self.return_period, action=action.get("action"))
            # frappe.msgprint(f"{resp}")
            # resp = json.loads(self.json_reply.replace("'", '"'))
            if not resp:
                frappe.msgprint(f"<b>{action.get('name')}</b> there is Some Error or No Data for {self.return_period}")
            else:
                frappe.msgprint(f"<b>{action.get('name')}</b> for Period {self.return_period} is Updated")
                self.process_gstr2a_response(response=resp, action=action.get("action"))

    def get_gstr2b_data(self):
        if not self.gstr2b_gen_date:
            for action in gstr2b_actions:
                resp = get_gstr2b(gstin=self.gstin, ret_period=self.return_period, action=action.get("action"))
                # resp = json.loads(self.json_reply.replace("'", '"'))
                if not resp:
                    frappe.msgprint(f"<b>{action.get('name')}</b> there is Some Error or No Data for {self.return_period}")
                else:
                    self.process_gstr2b_response(response=resp)
        else:
            frappe.throw(f"GSTR2B Already Generated on {self.gstr2b_gen_date}")

    def process_gstr2b_response(self, response):
        data = response.get("data")
        gstr2b_date = datetime.strptime(data.get("gendt"), "%d-%m-%Y").date()
        frappe.db.set_value(self.doctype, self.name, "gstr2b_gen_date", gstr2b_date)
        data_lists = ["b2b", "b2ba", "cdnr", "cdnra", "isd", "isda", "impg", "impgsez"]
        docs = data.get("docdata")
        for dt in data_lists:
            frappe.msgprint(f"Processing {dt}")
            if docs.get(dt, "") != "":
                for row in docs.get(dt):
                    self.update_gstr2b_for_gstin(row, dt, gstr2b_date)

    def update_gstr2b_for_gstin(self, row, dt, gstr2b_date):
        sup_cond = ""
        values = {}
        if dt != "impg":
            sup_cond = " AND gi.party_gstin = %(party_gstin)s AND g2.return_period = %(return_period)s"
            values = {"party_gstin": row.get('ctin'), "return_period": row.get('supprd')}
        if dt == "cdnr":
            invoices = row.get("nt")
            inv_no_field = "ntnum"
        elif dt == "impg":
            invoices = [row]
            inv_no_field = "boenum"
        else:
            invoices = row.get("inv")
            inv_no_field = "inum"

        inv_nos = [inv.get(inv_no_field) for inv in invoices]
        if not inv_nos:
            return

        # Single query across all invoice numbers for this row, instead of one
        # query per invoice inside the loop below.
        values["inv_nos"] = inv_nos
        gstr2_rows = frappe.db.sql(f"""SELECT g2.name, gi.name as row_name, gi.idx, gi.supplier_invoice_no
            FROM `tabGSTR2A RIGPL` g2, `tabGSTR2 Return Invoices` gi
            WHERE gi.parent = g2.name AND gi.supplier_invoice_no IN %(inv_nos)s {sup_cond}""", values, as_dict=1)
        rows_by_invoice_no = {}
        for r in gstr2_rows:
            rows_by_invoice_no.setdefault(r.supplier_invoice_no, []).append(r)

        for inv in invoices:
            inv_no = inv.get(inv_no_field)
            matched = rows_by_invoice_no.get(inv_no, [])
            if len(matched) < 1:
                frappe.throw(f"No GSTR2 Data found for GSTIN: {row} and {dt}")
            else:
                for m in matched:
                    frappe.db.set_value("GSTR2 Return Invoices", m.row_name, "gstr2b_date", gstr2b_date)
                    frappe.db.set_value("GSTR2 Return Invoices", m.row_name, "gstr2b_period", self.return_period)

    def analyse_data(self, dont_save=0):
        self.link_docs()
        if not self.invoices:
            frappe.throw(f"No Data in Invoices for {self.name}")
        f_tax_amt, unf_tax_amt, f_tax_val, unf_tax_val, ma_tax_val, unma_tax_val, tot_tax_val = 0, 0, 0, 0, 0, 0, 0
        for d in self.invoices:
            tax_amount = flt(d.cgst_amount) + flt(d.sgst_amount) + flt(d.igst_amount) + flt(d.cess_amount)
            if d.fully_matched == 1:
                ma_tax_val += flt(d.taxable_value)
            else:
                if d.linked_document_type and d.linked_document_name:
                    ma_tax_val += flt(d.linked_doc_taxable_value)
                else:
                    unma_tax_val += flt(d.taxable_value)
                if 0.98 <=(d.linked_doc_taxable_value/(d.taxable_value+1))<=1.02 and \
                        0.98 <= (d.linked_doc_grand_total/(d.grand_total+1)) <= 1.02:
                    d.fully_matched = 1
            if d.filing_status_gstr1 == 1:
                tot_tax_val += flt(d.taxable_value)
                f_tax_amt += tax_amount
                f_tax_val += flt(d.taxable_value)
            else:
                unf_tax_amt += tax_amount
                unf_tax_val += flt(d.taxable_value)
                if d.linked_document_type and d.linked_document_name and d.linked_doc_status == "Submitted":
                    frappe.msgprint(f"For Row# {d.idx} the Returns are Not Filed but "
                                    f"{frappe.get_desk_link(d.linked_document_type, d.linked_document_name)} is Submitted")
        self.filed_tax_amount = f_tax_amt
        self.unfiled_tax_amount = unf_tax_amt
        self.filed_taxable_value = f_tax_val
        self.unfiled_taxable_value = unf_tax_val
        self.matched_taxable_value = ma_tax_val
        self.unmatched_taxable_value = unma_tax_val
        self.total_taxable_value = tot_tax_val
        if dont_save != 1:
            self.save()

    def link_docs(self):
        for d in self.invoices:
            d.party_type, d.party, d.party_name = get_party_from_gstin("Supplier", d.party_gstin)
            if d.party and d.party_type == "Supplier":
                if not d.linked_document_type:
                    d.linked_document_type, d.linked_document_name = get_pi_frm_supplier_inv_no(d.party,
                                                                                                d.supplier_invoice_no)
                else:
                    ldt = frappe.get_doc(d.linked_document_type, d.linked_document_name)
                    if d.linked_document_type == "Purchase Invoice":
                        d.linked_doc_taxable_value = ldt.base_total
                        d.linked_doc_grand_total = ldt.base_grand_total
                    else:
                        d.linked_doc_grand_total = ldt.total_debit
                        d.linked_doc_taxable_value = 0
                    if ldt.docstatus == 1:
                        d.linked_doc_status = "Submitted"
                    elif ldt.docstatus == 0:
                        d.linked_doc_status = "Draft"
                    else:
                        frappe.throw(f"Unknown Document Status for Row# {d.idx} and "
                                     f"{frappe.get_desk_link(d.linked_doc_status, d.linked_document_name)}")

    def process_gstr2a_response(self, response, action):
        resp = frappe._dict(response)
        resp_data = resp.get(action.lower())
        if resp_data:
            self.create_new_table(resp_data)
        self.link_docs()

    def create_new_table(self, resp):
        for d in resp:
            row = frappe._dict({})
            row_list = update_gstin_data(row, d)
            self.update_invoice_table(row_list)

    def update_invoice_table(self, row_list):
        for data in row_list:
            data = frappe._dict(data)
            self.append("invoices", data.copy())


def update_gstin_data(row, gstin_resp):
    row_list = []
    if gstin_resp.get("portcd"):
        row["filing_status_gstr1"] = 1
        row["party_gstin"] = gstin_resp.get("portcd")
        row["supplier_invoice_no"] = gstin_resp.get("benum")
        row["note_type"] = "Bill of Entry"
        row["supplier_invoice_date"] = datetime.strptime(gstin_resp.get("bedt"), '%d-%m-%Y').date()
        row["taxable_value"] = gstin_resp.get("txval")
        row["igst_amount"] = gstin_resp.get("iamt")
        row["cess_amount"] = gstin_resp.get("csamt")
        row_list.append(row.copy())
    elif gstin_resp.get("gstin_deductor"):
        row["filing_status_gstr1"] = 1
        row["party_gstin"] = gstin_resp.get("gstin_deductor")
        row["note_type"] = "TDS"
        row["taxable_value"] = gstin_resp.get("amt_ded")
        row["igst_amount"] = gstin_resp.get("iamt")
        row["cess_amount"] = gstin_resp.get("csamt")
        row["filing_period_gstr1"] = gstin_resp.get("month")
        row["party_name"] = gstin_resp.get("deductor_name")
        row_list.append(row.copy())
    elif gstin_resp.get("sup_gstin"):
        row["filing_status_gstr1"] = 1
        row["party_gstin"] = gstin_resp.get("sup_gstin")
        row["note_type"] = "TCS"
        row["taxable_value"] = gstin_resp.get("amt")
        row["igst_amount"] = gstin_resp.get("iamt")
        row["cess_amount"] = gstin_resp.get("csamt")
        row["filing_period_gstr1"] = gstin_resp.get("month")
        row["party_name"] = gstin_resp.get("sup_name")
        row_list.append(row.copy())
    else:
        row["filing_status_gstr1"] = 1 if gstin_resp.get("cfs") == 'Y' else 0
        row["filing_date_gstr1"] = datetime.strptime(gstin_resp.get("fldtr1"), '%d-%b-%y').date() \
            if gstin_resp.get("fldtr1") else ""
        row["filing_status_gstr3b"] = 1 if gstin_resp.get("cfs3b") == 'Y' else 0
        row["filing_period_gstr1"] = gstin_resp.get("flprdr1")
        row["party_gstin"] = gstin_resp.get("ctin")
        for inv in gstin_resp.get("inv") or gstin_resp.get("nt"):
            row_with_items = update_invoice_data(row, inv)
            for full_row in row_with_items:
                row_list.append(full_row)
    return row_list


def update_invoice_data(row, inv):
    row_list = []
    if inv.get("nt_num"):
        row["note_type"] = "Credit Note" if inv.get("ntty") == "C" else "Debit Note"
        row["supplier_invoice_no"] = inv.get("nt_num")
    elif inv.get("inum"):
        row["supplier_invoice_no"] = inv.get("inum")
        row["note_type"] = "Invoice"
    if inv.get("idt"):
        row["supplier_invoice_date"] = datetime.strptime(inv.get("idt"), '%d-%m-%Y').date()
    elif inv.get("nt_dt"):
        row["supplier_invoice_date"] = datetime.strptime(inv.get("nt_dt"), '%d-%m-%Y').date()
    row["grand_total"] = inv.get("val")
    row["reverse_charge_applicable"] = 1 if inv.get("rchrg") == 'Y' else 0
    row["invoice_type"] = get_invoice_type(inv.get("inv_typ"))
    row["type_of_amendment"] = get_type_of_amend(inv.get("atyp"))
    row["return_period_amendment"] = inv.get("aspd")
    row["irn_number"] = inv.get("irn")
    if inv.get("irngendate"):
        row["irn_generation_date"] = datetime.strptime(inv.get("irngendate", "01-01-1900"), '%d-%m-%Y').date()
    row["differential_percentage"] = inv.get("diff_percent")
    items = inv.get("itms")
    item_row = update_item_data(row, items)
    for it in item_row:
        row_list.append(it.copy())
    return row_list


def update_item_data(row, item_row):
    item_list = []
    for it in item_row:
        itd = it.get("itm_det")
        row["taxable_value"] = itd.get("txval")
        row["cgst_amount"] = itd.get("camt")
        row["sgst_amount"] = itd.get("samt")
        row["igst_amount"] = itd.get("iamt")
        row["cess_amount"] = itd.get("csamt")
        row["tax_rate"] = itd.get("rt")
        item_list.append(row.copy())
    return item_list


def get_party_from_gstin(ptype, gstin):
    party_type = ""
    party = ""
    party_name = ""
    add_list = frappe.db.sql("""SELECT ad.name, ad.address_title, dl.link_doctype as party_type, 
    dl.link_name as party, ad.gstin
    FROM `tabAddress` ad, `tabDynamic Link` dl WHERE dl.parenttype = 'Address' AND dl.parent = ad.name
    AND ad.gstin = '%s'""" % gstin, as_dict=1)
    if add_list:
        if len(add_list) > 1:
            count = 0
            # More than one DL linked to Address, so check if only 1 party type then return
            for d in add_list:
                if d.party_type == ptype:
                    party_type, party, party_name = d.party_type, d.party, d.address_title
                    count += 1
            if count < 2:
                return party_type, party, party_name
            else:
                # More than 1 Party Found Now if there is inv_no then find by Inv No else return first one
                return party_type, party, party_name
        else:
            return add_list[0].party_type, add_list[0].party, add_list[0].address_title
    else:
        return party_type, party, party_name


def get_pi_frm_supplier_inv_no(supplier, supplier_inv_no):
    dt = ""
    dn = ""
    search_list = frappe.db.sql("""SELECT name FROM `tabPurchase Invoice` WHERE docstatus != 2 AND supplier = '%s'
    AND bill_no = '%s'""" % (supplier, supplier_inv_no), as_dict=1)
    if search_list:
        dt = "Purchase Invoice"
        dn = search_list[0].name
    return dt, dn

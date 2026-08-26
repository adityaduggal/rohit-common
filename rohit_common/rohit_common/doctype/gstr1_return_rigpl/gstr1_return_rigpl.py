# -*- coding: utf-8 -*-
# Copyright (c) 2021, Rohit Industries Ltd. and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
import json
from datetime import datetime
from frappe.model.document import Document
from frappe.utils import getdate, flt
from erpnext.accounts.utils import get_fiscal_year
from ....utils.common import update_child_table
from ....utils.rohit_common_utils import check_dynamic_link
from ....utils.accounts_utils import get_base_doc_no, get_taxes_from_sid, get_gst_si_type, get_gst_export_fields, \
    get_gst_jv_type, get_taxes_from_jvd, get_linked_type_from_jv, get_hsn_sum_frm_si, get_inv_status, \
    get_invoice_uploader, guess_correct_address, get_base_doc_frm_docname
from ...india_gst_api.common import gst_return_period_validation, get_dates_from_return_period
from ...india_gst_api.gst_public_api import track_return_whitebooks, get_arn_status, \
    get_gstr1_whitebooks

gstr1_actions = [
    {"action": "AT", "name": "Advances Tax", "tbl": "at_invoices"},
    {"action": "ATA", "name": "Advances Tax Amendments", "tbl": "ataa_invoices"},
    {"action": "B2B", "name": "B2B", "tbl": "b2b_invoices"},
    {"action": "B2BA", "name": "B2B Amendments", "tbl": "b2ba_invoices"},
    {"action": "B2CL", "name": "B2BC Large", "tbl": "b2cl_invoices"},
    {"action": "B2CLA", "name": "B2C Large Amendments", "tbl": "b2cla_invoices"},
    {"action": "B2CS", "name": "B2C Small", "tbl": "b2c_invoices"},
    {"action": "B2CSA", "name": "B2C Small Amendments", "tbl": "b2csa_invoices"},
    {"action": "CDNR", "name": "CDN Registered", "tbl": "cdn_b2b"},
    {"action": "CDNRA", "name": "CDN Registered Amendments", "tbl": "cdb_b2ba"},
    {"action": "CDNUR", "name": "CDN Un-Registered", "tbl": "cdn_b2c"},
    {"action": "CDNURA", "name": "CDN Un=Registered Amendments", "tbl": "cdn_b2ca"},
    {"action": "DOCISS", "name": "Docs Issued", "tbl": "docs_issued"},
    {"action": "EINV", "name": "e-Invoices", "tbl": "einv"},
    {"action": "EXP", "name": "Export Invoices", "tbl": "export_invoices"},
    {"action": "EXPA", "name": "Export Invoices Amendments", "tbl": "export_amend"},
    {"action": "HSNSUM", "name": "GSTR1 HSN Summary", "tbl": "hsn_sum"},
    {"action": "NIL", "name": "Nil Supplies", "tbl": "nil_sup"},
    {"action": "TXP", "name": "Tax Paid", "tbl": "adv_adj"},
    {"action": "TXPA", "name": "Tax Paid Amendments", "tbl": "adv_adja"}
]

# {"action": "RETSTATUS", "name": "GSTR1 Status", "tbl": "none"}
# {"action": "RETSUM", "name": "GSTR1 Summary", "tbl": "none"}
# {"action": "RETSUBMIT", "name": "Submit GSTR1", "tbl": "none"}
# {"action": "RESET", "name": "Reset GSTR1"}
# {"action": "RESTSAVE", "name": "Save GSTR1"}


class GSTR1ReturnRIGPL(Document):

    def get_gstr1_details(self):
        if self.is_new() == 1:
            frappe.throw("Save the document before Getting GSTR1 Data")
        first_date_text = self.return_period[2:] + "-" + self.return_period[:2] + "-" + "01"
        fy = get_fiscal_year(date=getdate(first_date_text)) # format for getdate is YYYY-MM-DD
        if not self.arn_number:
            # If GSTR1 is not Filed then Check if Filed and if Filed then get the ARN and other details and verify
            # from GST Network
            return_status = track_return_whitebooks(gstin=self.gstin, fiscal_year=fy[0], type_of_return="R1")
            self.arn_number, self.filing_status, self.filing_date, self.mode_of_filing = \
                get_arn_status(ret_status_json=return_status, type_of_return="GSTR1", ret_period=self.return_period)
            if not self.arn_number:
                self.filing_status = "Not Filed"
                frappe.msgprint(f"{self.name} is Not Filed on GST Portal we can file it from here")
            else:
                self.save()
            # If the GSTR1 is not filed then SAVE the data after validation of the data on GSTN Portal
        else:
            # If GSTR1 arn is there then verify the data with generated GSTR1 with ERP and GSTR Network
            # Also disable all the tables for editing
            # gstr1_actions = [{"action": "B2B", "name": "B2B", "tbl": "b2b_invoices"}]
            for act_dict in gstr1_actions:
                resp = get_gstr1_whitebooks(gstin=self.gstin, ret_period=self.return_period,
                                            action=act_dict.get("action"))
                # resp = json.loads(self.json_reply.replace("'", '"'))
                if not resp:
                    frappe.msgprint(f"<b>{act_dict.get('name')}</b> there is Some Error or No Data "
                                    f"for {self.return_period}")
                else:
                    self.process_gstr1(response=resp, act_dict=act_dict)
                    frappe.msgprint(f"<b>{act_dict.get('name')}</b> for Period {self.return_period} is Fetched")
            self.reload()
            self.save()

    def process_gstr1(self, response, act_dict):
        action = act_dict.get("action")
        act_desc = act_dict.get("name")
        resp_data = response.get(action.lower())
        if not self.get(act_dict.get("tbl"), []):
            if resp_data:
                frappe.throw(f"For {act_desc} there is Data in GST Network but Table for the Same is Empty")
        else:
            if not resp_data:
                frappe.throw(f"For {act_desc} there is No Data in GST Network but Table for the Same has Data")
            else:
                for d in response.get(action.lower()):
                    d = frappe._dict(d)
                    match_and_update_details_from_gstin(gstin_resp=d, gstr1_doc=self, act_dict=act_dict)

    def generate_synopsis(self):
        syn_txt = ""
        si_tables = [{"tbl": "b2b_invoices", "name": "B2B Invoices"},
                     {"tbl": "b2cl_invoices", "name": "B2C Large Invoices"},
                     {"tbl": "cdn_b2b", "name": "Credit/ Debit Notes (Registered)"},
                     {"tbl": "cdn_b2c", "name": "Credit/ Debit Notes (Un-Registered)"},
                     {"tbl": "export_invoices", "name": "Export Invoices"},
                     {"tbl": "b2c_invoices", "name": "B2C Invoices"}]
        for txt in si_tables:
            tot_docs, inv_val, tax_val, igst, sgst, cgst = 0, 0, 0, 0, 0, 0
            syn_txt += f"<br> <b>{txt.get('name')} </b><br>"
            if self.get(txt.get("tbl")):
                for row in self.get(txt.get("tbl")):
                    tot_docs += 1
                    inv_val += row.total_invoice_value
                    tax_val += row.taxable_value
                    igst += row.igst
                    sgst += row.sgst
                    cgst += row.cgst
                syn_txt += f"Total Documents = {tot_docs} <br>" \
                           f"Total Value = {round(inv_val,2)} <br>Total Taxable Value = {round(tax_val,2)} <br>" \
                           f"Total Tax Liability = {round(igst+cgst+sgst,2)} <br>Total IGST = {round(igst,2)} <br>" \
                           f"Total SGST = {round(sgst,2)} <br>Total CGST = {round(cgst,2)}"
            syn_txt += "<hr>"
        self.synopsis_text = syn_txt

    def generate_hsn_summary(self):
        self.set("hsn_summary", [])
        si_tables = ["b2b_invoices", "b2cl_invoices", "cdn_b2c", "cdn_b2b", "export_invoices", "b2c_invoices"]
        hsn_list = []
        for tbl in si_tables:
            if self.get(tbl):
                for row in self.get(tbl):
                    if row.document_type == "Sales Invoice":
                        hsn_sum = get_hsn_sum_frm_si(row.document_number)
                        if hsn_list:
                            for hsn in hsn_sum:
                                found = 0
                                for base_hsn in hsn_list:
                                    if base_hsn.hsn == hsn.hsn and base_hsn.uom == hsn.uom:
                                        found = 1
                                        base_hsn.total_quantity += hsn.total_quantity
                                        base_hsn.total_taxable_value += hsn.total_taxable_value
                                        base_hsn.igst += hsn.igst
                                        base_hsn.cgst += hsn.cgst
                                        base_hsn.sgst += hsn.sgst
                                        base_hsn.cess += hsn.cess
                                        base_hsn.total_value += hsn.total_value
                                if found == 0:
                                    hsn_list.append(hsn.copy())
                        else:
                            for hsn in hsn_sum:
                                hsn_list.append(hsn.copy())
        hsn_list = sorted(hsn_list, key=lambda i: i["hsn"], reverse=0)
        update_child_table(doc=self, table_name="hsn_summary", row_list=hsn_list)


    def validate(self):
        if self.is_new() != 1:
            if self.fully_validated != 1:
                self.validate_si_tables()
                self.generate_synopsis()
                self.generate_hsn_summary()
        else:
            gst_return_period_validation(return_period=self.return_period)

    def on_submit(self):
        self.validate_export_invoices()
        self.validate_si_tables(submit=1)
        frappe.throw("Submission is Not Allowed for the Time Being")

    def validate_si_tables(self, submit=0):
        si_tables = ["b2b_invoices", "b2cl_invoices", "cdn_b2c", "cdn_b2b", "export_invoices", "b2c_invoices"]
        tbls_fully_validated = 0
        empty_tables = 0
        if self.filing_status == "Filed":
            filed = 1
        else:
            filed = 0
        for tbl in si_tables:
            no_chk_rows = 0
            row_list = []
            if not self.get(tbl):
                empty_tables += 1
            else:
                for d in self.get(tbl):
                    if filed == 1:
                        if not d.invoice_checksum:
                            no_chk_rows += 1
                            row_list.append(d.idx)
                    else:
                        no_chk_rows += 1
                    if d.document_type == "Sales Invoice":
                        d.receiver_address = frappe.get_value(d.document_type, d.document_number, "customer_address")
                        d.receiver_gstin = frappe.get_value(d.document_type, d.document_number, "billing_address_gstin")
                    elif d.document_type == "Journal Entry":
                        link_dt, link_dn = get_linked_type_from_jv(jv_name=d.document_number)
                        # Once the linked Party is obtained we can automatically fill the address by guess
                        # If only 1 address is there then its simple and if multiple address are there then
                        # We would need to check the address used max for billing address in that period
                        if not d.receiver_address:
                            d.receiver_address = guess_correct_address(linked_dt=link_dt, linked_dn=link_dn)
                        check_dynamic_link(parenttype="Address", parent=d.receiver_address, link_doctype=link_dt,
                                           link_name=link_dn)
                        d.receiver_gstin = frappe.get_value("Address", d.receiver_address, "gstin")
                    else:
                        frappe.throw(f"{d.document_type} mentioned in Row# {d.idx} is Not Supported")
                    d.receiver_name = frappe.get_value("Address", d.receiver_address, "address_title")
                if no_chk_rows > 0:
                    message = f"There are {no_chk_rows} rows in Table: {tbl} where GSTIN Checksum is missing But since return is filed \
                    you wont be able to Submit the Document. Pull the Data from GSTIN Network to Submit."
                    if no_chk_rows != len(row_list):
                        message += f" The rows are {str(row_list)}"
                    if submit == 1:
                        frappe.throw(message)
                    elif filed == 1:
                        frappe.msgprint(message)
                        print(message)
                else:
                    tbls_fully_validated += 1
        if tbls_fully_validated == len(si_tables) - empty_tables and tbls_fully_validated > 0:
            frappe.msgprint(f"GSTR1 Return: {self.name} is now Fully validated and Can be Submitted")
            frappe.db.set_value(self.doctype, self.name, "fully_validated", 1)
            self.reload()
        else:
            frappe.db.set_value(self.doctype, self.name, "fully_validated", 0)


    def validate_export_invoices(self):
        for d in self.export_invoices:
            if not d.gst_payment or not d.port_code or not d.shipping_bill_no or not d.shipping_bill_date:
                frappe.throw(f"For Row# {d.idx} in Export Invoices either GST Payment or Port Code or SHB Details "
                             f"are not mentioned.")

    def get_details(self):
        self.clear_all_tables()
        self.generate_gstr1()
        self.save()


    def generate_gstr1(self):
        frm_dt, to_dt = get_dates_from_return_period(self.return_period)
        self.get_invoices(start_date=frm_dt, end_date=to_dt)
        self.get_jv_entries(start_date=frm_dt, end_date=to_dt)
        frappe.msgprint("Updated All Tables")

    def get_jv_entries(self, start_date, end_date):
        gst_set = frappe.get_doc("GST Settings", "GST Setting")
        gst_acc = []
        cdn_b2b_list = []
        for d in gst_set.gst_accounts:
            gst_acc.append(d.cgst_account)
            gst_acc.append(d.sgst_account)
            gst_acc.append(d.igst_account)
            gst_acc.append(d.cess_account)
        jv_dict = frappe.db.sql("""SELECT jv.name, jvd.account
        FROM `tabJournal Entry` jv, `tabJournal Entry Account` jvd
        WHERE jvd.parent = jv.name AND jv.docstatus=1 AND jv.posting_date >= %(start_date)s AND jv.posting_date <= %(end_date)s
        ORDER BY jv.posting_date, jv.name, jvd.idx""", {"start_date": start_date, "end_date": end_date}, as_dict=1)
        jv_templ_list = []
        for jv in jv_dict:
            if jv.account in gst_acc:
                jv_templ_list.append(jv.name)
        jv_list = []
        for i in jv_templ_list:
            if i not in jv_list:
                jv_list.append(i)
        # Above list is of all JV in period where GST Accounts are there. Now JV would be Credit or Debit if it has
        # Creditor or Debtor as a Row in JV Accounts
        jv_cdn = []
        for jv in jv_list:
            jvd = frappe.get_doc("Journal Entry", jv)
            for acc in jvd.accounts:
                if acc.party_type == "Customer" and jvd.name not in jv_cdn:
                    jv_cdn.append(jv)
        for jv in jv_cdn:
            row = get_row_from_jv_name(jv)
            cdn_b2b_list.append(row.copy())
        update_child_table(doc=self, table_name="cdn_b2b", row_list=cdn_b2b_list)

    def get_invoices(self, start_date, end_date):
        inv_list = frappe.db.sql("""SELECT name FROM `tabSales Invoice` WHERE docstatus = 1 AND posting_date >= %(start_date)s
        AND posting_date <= %(end_date)s AND company_gstin = %(gstin)s
        ORDER BY customer, name""", {"start_date": start_date, "end_date": end_date, "gstin": self.gstin}, as_dict=1)
        b2b_list = []
        b2cl_list = []
        b2c_list = []
        exp_list = []
        cdn_b2b_list = []
        cdn_b2c_list = []
        for inv in inv_list:
            row = get_row_from_inv_name(inv.name)
            if row:
                if row["invoice_type_2"] == "b2b":
                    b2b_list.append(row.copy())
                elif row["invoice_type_2"] == "b2cl":
                    b2cl_list.append(row.copy())
                elif row["invoice_type_2"] == "b2c":
                    b2c_list.append(row.copy())
                elif row["invoice_type_2"] == "export":
                    exp_list.append(row.copy())
                elif row["invoice_type_2"] == "cdn_b2c":
                    cdn_b2c_list.append(row.copy())
                elif row["invoice_type_2"] == "cdn_b2b":
                    cdn_b2b_list.append(row.copy())
                else:
                    frappe.throw(f"Unknown Invoice Type for {row.document_number}")
        update_child_table(doc=self, table_name="b2b_invoices", row_list=b2b_list)
        update_child_table(doc=self, table_name="b2cl_invoices", row_list=b2cl_list)
        update_child_table(doc=self, table_name="b2c_invoices", row_list=b2c_list)
        update_child_table(doc=self, table_name="export_invoices", row_list=exp_list)
        update_child_table(doc=self, table_name="cdn_b2b", row_list=cdn_b2b_list)
        update_child_table(doc=self, table_name="cdn_b2c", row_list=cdn_b2c_list)

    def clear_all_tables(self):
        si_tables = ["b2b_invoices", "b2cl_invoices", "cdn_b2c", "cdn_b2b", "export_invoices", "b2c_invoices",
                     "hsn_summary"]
        self.synopsis_text = ""
        for si in si_tables:
            self.set(si, [])


def match_and_update_details_from_gstin(gstin_resp, gstr1_doc, act_dict):
    if gstin_resp.get("sply_ty", None):
        # Case of B2C
        si_state_wise = frappe.db.sql("""SELECT gs.name, gs.idx, gs.receiver_address, gs.taxable_value, gs.igst, gs.sgst, gs.cgst, gs.cess
            FROM `tabGSTR1 Return Invoices` gs, `tabAddress` ad1, `tabState` st
            WHERE gs.receiver_address = ad1.name AND st.name = ad1.state_rigpl AND st.state_code_numeric = %(state_code)s
            AND gs.parent = %(parent)s AND gs.parenttype = %(parenttype)s AND gs.parentfield = %(parentfield)s
            ORDER BY gs.idx""", {
                "state_code": gstin_resp.get("pos"),
                "parent": gstr1_doc.name,
                "parenttype": gstr1_doc.doctype,
                "parentfield": act_dict.get("tbl"),
            }, as_dict=1)
        if not si_state_wise:
            frappe.throw(f"There is No Data for State Code = {gstin_resp.get('pos')} in our System whereas in GSTIN There is for {act_dict.get('action')}")
        else:
            taxable, igst, cgst, sgst, cess = 0, 0, 0, 0, 0
            row_list = []
            for inv in si_state_wise:
                taxable += inv.taxable_value
                igst += inv.igst
                cgst += inv.cgst
                sgst += inv.sgst
                cess += inv.cess
                row_list.append(inv.idx)
            if int(taxable) != int(flt(gstin_resp.get("txval"))):
                frappe.throw(f"For State Code {gstin_resp.get('pos')} there is a Difference in Taxable Value \
                        GST= {gstin_resp.get('txval')} Our System = {taxable} check rows {str(row_list)}")
            elif int(igst) != int(flt(gstin_resp.get("iamt"))):
                frappe.throw(f"For State Code {gstin_resp.get('pos')} there is a Difference in IGST Value \
                        GST= {gstin_resp.get('iamt')} Our System = {igst} check rows {str(row_list)}")
            elif int(sgst) != int(flt(gstin_resp.get("samt"))):
                frappe.throw(f"For State Code {gstin_resp.get('pos')} there is a Difference in SGST Value \
                        GST= {gstin_resp.get('samt')} Our System = {sgst} check rows {str(row_list)}")
            elif int(cgst) != int(flt(gstin_resp.get("camt"))):
                frappe.throw(f"For State Code {gstin_resp.get('pos')} there is a Difference in CGST Value \
                        GST= {gstin_resp.get('camt')} Our System = {cgst} check rows {str(row_list)}")
            elif int(cess) != int(flt(gstin_resp.get("csamt"))):
                frappe.throw(f"For State Code {gstin_resp.get('pos')} there is a Difference in Cess Value \
                        GST= {gstin_resp.get('csamt')} Our System = {cess} check rows {str(row_list)}")
            else:
                for inv in si_state_wise:
                    frappe.db.set_value("GSTR1 Return Invoices", inv.name, "invoice_status", get_inv_status(gstin_resp.get('flag')))
                    frappe.db.set_value("GSTR1 Return Invoices", inv.name, "invoice_checksum", gstin_resp.get("chksum"))
    else:
        si_gstin = frappe.db.sql("""SELECT * FROM `tabGSTR1 Return Invoices` WHERE parent = %(parent)s AND parenttype = %(parenttype)s
        AND parentfield = %(parentfield)s AND receiver_gstin = %(receiver_gstin)s ORDER BY idx""", {
            "parent": gstr1_doc.name,
            "parenttype": gstr1_doc.doctype,
            "parentfield": act_dict.get("tbl"),
            "receiver_gstin": gstin_resp.ctin,
        }, as_dict=1)
        if si_gstin:
            if gstin_resp.get("nt"):
                if len(si_gstin) != len(gstin_resp.nt):
                    frappe.throw(f"For GSTIN: {gstin_resp.ctin} Total Invoices in GST= {len(gstin_resp.nt)} Whereas in "
                                 f"System the Total Invoices = {len(si_gstin)}.<br>Please Correct the Error to Proceed"
                                 f"<br><br> The GST Data is {gstin_resp}")
                for cdn in gstin_resp.nt:
                    check_invoice_integrity(gst_inv_data=cdn, local_inv_data=si_gstin)
            else:
                if len(si_gstin) != len(gstin_resp.inv):
                    frappe.throw(f"For GSTIN: {gstin_resp.ctin} Total Invoices in GST= {len(gstin_resp.inv)} Whereas in "
                                 f"System the Total Invoices = {len(si_gstin)}.<br>Please Correct the Error to Proceed"
                                 f"<br><br> The GST Data is {gstin_resp}")
                for inv in gstin_resp.inv:
                    check_invoice_integrity(gst_inv_data=inv, local_inv_data=si_gstin)
        else:
            # GSTIN is not found so search the invoice number and change the Billing Address GSTIN
            # As per the GSTR1 to make the data correct in both sides. In Case of Credit Notes we might need to change
            # address
            frappe.msgprint(f"GSTIN: {gstin_resp.ctin} is Not Mentioned in Any Invoice so Searching by Invoice No of GST Network")
            if gstin_resp.get("inv"):
                # Batch the local-invoice lookup into a single query, instead of one
                # frappe.db.sql() per GST-portal invoice.
                inv_no_map = {
                    inv.get("inum"): get_base_doc_frm_docname(dt="Sales Invoice", dn=inv.get("inum"))
                    for inv in gstin_resp.inv
                }
                inv_nos = list(set(inv_no_map.values()))
                local_rows = frappe.db.sql("""SELECT * FROM `tabGSTR1 Return Invoices` WHERE parent = %(parent)s
                    AND parenttype = %(parenttype)s AND parentfield = %(parentfield)s
                    AND invoice_number IN %(inv_nos)s ORDER BY idx""", {
                        "parent": gstr1_doc.name,
                        "parenttype": gstr1_doc.doctype,
                        "parentfield": act_dict.get("tbl"),
                        "inv_nos": inv_nos,
                    }, as_dict=1)
                local_rows_by_invoice = {}
                for row in local_rows:
                    local_rows_by_invoice.setdefault(row.invoice_number, []).append(row)

                for inv in gstin_resp.inv:
                    inv_no = inv_no_map[inv.get("inum")]
                    si_from_si_no = local_rows_by_invoice.get(inv_no, [])
                    if si_from_si_no:
                        check_invoice_integrity(gst_inv_data=inv, local_inv_data=si_from_si_no)
                    else:
                        frappe.throw(f"For GSTIN: {gstin_resp.ctin} there is NO Invoice with Invoice No {inv_no} in Our System")
            else:
                frappe.msgprint(f"For GSTIN: {gstin_resp.ctin} No Linked Invoices Found")


def check_invoice_integrity(gst_inv_data, local_inv_data):
    inv = gst_inv_data
    inv_found = 0
    for row in local_inv_data:
        if inv.get("sbnum"):
            # Case of Export Invoices
            base_doc_no = get_base_doc_frm_docname(dt=row.document_type, dn=inv.get("inum"))
            if inv.get("sbnum") == row.shipping_bill_no or base_doc_no == row.invoice_number:
                inv_found = 1
                gst_shb_date = datetime.strptime(inv.get("sbdt"), "%d-%m-%Y").date()
                if gst_shb_date != row.shipping_bill_date:
                    frappe.throw(f"For Row# {row.idx} SHB Date on GST = {gst_shb_date} whereas in System its {row.shipping_bill_date}")
                elif inv.get("val") != row.total_invoice_value:
                    frappe.throw(f"For Row# {row.idx} Total Invoice Value does "
                                 f"not Match with GST Network Inv Value <b>{inv.get('val')}</b>")
                else:
                    frappe.db.set_value("GSTR1 Return Invoices", row.name, "invoice_status",
                                        get_inv_status(inv.get('flag')))
                    frappe.db.set_value("GSTR1 Return Invoices", row.name, "invoice_checksum", inv.get("chksum"))
        else:
            if inv.get("nt_num"):
                # Case of Credit and Debit Notes Registered
                base_doc_no = get_base_doc_frm_docname(dt=row.document_type, dn=inv.get("nt_num"))
                if base_doc_no == row.invoice_number:
                    inv_found = 1
                    gst_inv_date = datetime.strptime(inv.get("nt_dt"), "%d-%m-%Y").date()

                    if abs(flt(inv.get("val")) - flt(row.total_invoice_value)) / flt(inv.get("val")) > 0.05:
                        frappe.throw(f"For Row# {row.idx} Total Invoice Value does "
                                     f"not Match with GST Network Inv Value <b>{inv.get('val')}</b>")
                    elif gst_inv_date != getdate(row.invoice_date):
                        frappe.throw(f"For Row# {row.idx} Invoice Date does not Match with GST Network "
                                     f"Inv Date <b>{gst_inv_date}</b>")
                    else:
                        frappe.db.set_value("GSTR1 Return Invoices", row.name, "invoice_status",
                                            get_inv_status(inv.get('flag')))
                        frappe.db.set_value("GSTR1 Return Invoices", row.name, "uploaded_by",
                                            get_invoice_uploader(inv.get('updby')))
                        frappe.db.set_value("GSTR1 Return Invoices", row.name, "invoice_checksum", inv.get("chksum"))
            else:
                base_doc_no = get_base_doc_frm_docname(dt=row.document_type, dn=inv.get("inum"))
                if base_doc_no == row.invoice_number:
                    inv_found = 1
                    gst_inv_date = datetime.strptime(inv.get("idt"), "%d-%m-%Y").date()
                    if inv.get("val") != row.total_invoice_value:
                        frappe.throw(f"For Row# {row.idx} Total Invoice Value does "
                                     f"not Match with GST Network Inv Value <b>{inv.get('val')}</b>")
                    elif gst_inv_date != getdate(row.invoice_date):
                        frappe.throw(f"For Row# {row.idx} Invoice Date does not Match with GST Network "
                                     f"Inv Date <b>{gst_inv_date}</b>")
                    else:
                        frappe.db.set_value("GSTR1 Return Invoices", row.name, "invoice_status",
                                            get_inv_status(inv.get('flag')))
                        frappe.db.set_value("GSTR1 Return Invoices", row.name, "uploaded_by",
                                            get_invoice_uploader(inv.get('updby')))
                        frappe.db.set_value("GSTR1 Return Invoices", row.name, "invoice_checksum", inv.get("chksum"))
    if inv_found != 1:
        if inv.get("nt_num"):
            inv_no = inv.get("nt_num")
        else:
            inv_no = inv.get("inum")
        frappe.throw(f"Document {inv_no} is Not Found. <br><br>GST Invoice Data is {gst_inv_data} <br> <br> Local Invoice Data is {local_inv_data}")


def get_row_from_jv_name(jv_name):
    row = frappe._dict({})
    jvd = frappe.get_doc("Journal Entry", jv_name)
    jv_type = get_gst_jv_type(jvd)
    if jv_type == "credit":
        note_type = "Credit"
    else:
        note_type = "Debit"
    tax_rate, sgst_amt, cgst_amt, igst_amt, cess_amt, net_amt = get_taxes_from_jvd(jvd, jv_type)
    row["is_credit_debit"] = 1
    row["note_type"] = note_type
    row["document_type"] = "Journal Entry"
    row["document_number"] = jvd.name
    row["invoice_number"] = get_base_doc_no(jvd)
    row["invoice_date"] = jvd.posting_date
    row["total_invoice_value"] = jvd.total_debit
    row["taxable_value"] = net_amt
    row["rate"] = tax_rate
    row["igst"] = igst_amt
    row["sgst"] = sgst_amt
    row["cgst"] = cgst_amt
    return row


def get_row_from_inv_name(inv_name):
    row = frappe._dict({})
    multi_factor = 1
    sid = frappe.get_doc("Sales Invoice", inv_name)
    inv_type = get_gst_si_type(sid)
    if inv_type == "cdn_b2b" or inv_type == "cdn_b2c":
        row["is_credit_debit"] = 1
        row["note_type"] = "Credit"
        multi_factor = -1

    elif inv_type == "export":
        row["export_sales"] = 1
        row["shipping_bill_no"], row["shipping_bill_date"], row["gst_payment"], row["port_code"] = get_gst_export_fields(sid)
    bad_doc = frappe.get_doc("Address", sid.customer_address)
    base_inv_no = get_base_doc_no(sid)
    tax_rate, sgst_amt, cgst_amt, igst_amt, cess_amt = get_taxes_from_sid(sid)
    row["invoice_type_2"] = inv_type
    row["invoice_type"] = "R-Regular B2B Invoices" # TODO make invoice Type dynamic instead of static
    row["receiver_address"] = sid.customer_address
    row["receiver_gstin"] = sid.billing_address_gstin
    row["document_type"] = "Sales Invoice"
    row["document_number"] = sid.name
    row["invoice_number"] = base_inv_no
    row["receiver_name"] = bad_doc.address_title
    row["invoice_date"] = sid.posting_date
    row["total_invoice_value"] = sid.base_grand_total * multi_factor
    row["rate"] = tax_rate
    row["taxable_value"] = sid.base_net_total * multi_factor
    row["igst"] = igst_amt * multi_factor
    row["sgst"] = sgst_amt * multi_factor
    row["cgst"] = cgst_amt * multi_factor
    return row

def correct_invoice_gst_as_per_gstr1(inv_no, corr_gstin):
    frappe.db.set_value("Sales Invoice", inv_no, "billing_address_gstin", corr_gstin)
    frappe.msgprint(f"Corrected SI# {inv_no} with Correct GSTIN {corr_gstin}")
    sid = frappe.get_doc("Sales Invoice", inv_no)
    if sid.amended_from:
        correct_invoice_gst_as_per_gstr1(inv_no=sid.amended_from, corr_gstin=corr_gstin)

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
    get_invoice_uploader, guess_correct_address, get_base_doc_frm_docname, get_gst_accounts_list
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

# The 6 tables used identically (same names, same order) by generate_hsn_summary,
# validate_si_tables, and clear_all_tables. NOT used by generate_synopsis, which
# needs a display name per table and lists cdn_b2b/cdn_b2c in the opposite order,
# or by clear_all_tables, which additionally clears "hsn_summary" - keep those
# separate rather than folding them into this constant.
GSTR1_SI_TABLES = ["b2b_invoices", "b2cl_invoices", "cdn_b2c", "cdn_b2b", "export_invoices", "b2c_invoices"]


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
        hsn_map = {}
        for tbl in GSTR1_SI_TABLES:
            for row in self.get(tbl) or []:
                if row.document_type == "Sales Invoice":
                    for hsn in get_hsn_sum_frm_si(row.document_number):
                        key = (hsn.hsn, hsn.uom)
                        base_hsn = hsn_map.get(key)
                        if base_hsn:
                            base_hsn.total_quantity += hsn.total_quantity
                            base_hsn.total_taxable_value += hsn.total_taxable_value
                            base_hsn.igst += hsn.igst
                            base_hsn.cgst += hsn.cgst
                            base_hsn.sgst += hsn.sgst
                            base_hsn.cess += hsn.cess
                            base_hsn.total_value += hsn.total_value
                        else:
                            hsn_map[key] = hsn.copy()
        hsn_list = sorted(hsn_map.values(), key=lambda i: i["hsn"], reverse=0)
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
        si_tables = GSTR1_SI_TABLES
        tbls_fully_validated = 0
        empty_tables = 0
        filed = 1 if self.filing_status == "Filed" else 0

        # Batch-fetch customer_address/billing_address_gstin for every Sales-Invoice-typed
        # row across all tables in one query, instead of 2 frappe.get_value() calls per row.
        si_names = {d.document_number for tbl in si_tables for d in (self.get(tbl) or [])
                    if d.document_type == "Sales Invoice"}
        si_info = {}
        if si_names:
            si_info = {row.name: row for row in frappe.get_all(
                "Sales Invoice", filters=[["name", "in", list(si_names)]],
                fields=["name", "customer_address", "billing_address_gstin"])}

        # Pass 1: resolve receiver_address/receiver_gstin per row (batched for Sales
        # Invoice rows; Journal Entry rows still need get_linked_type_from_jv/
        # guess_correct_address/check_dynamic_link per row - those aren't simple field
        # reads, see TODOS.md "check_dynamic_link runs unconditionally on every JV-linked row").
        address_names = set()
        for tbl in si_tables:
            for d in self.get(tbl) or []:
                if d.document_type == "Sales Invoice":
                    si_row = si_info.get(d.document_number)
                    if not si_row:
                        frappe.throw(f"Sales Invoice {d.document_number} referenced in Row# {d.idx} "
                                     f"of {tbl} Not Found")
                    d.receiver_address = si_row.customer_address
                    d.receiver_gstin = si_row.billing_address_gstin
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
                if d.receiver_address:
                    address_names.add(d.receiver_address)

        # Batch-fetch address_title for every resolved receiver_address, instead of 1
        # frappe.get_value() call per row.
        address_titles = {}
        if address_names:
            address_titles = {row.name: row.address_title for row in frappe.get_all(
                "Address", filters=[["name", "in", list(address_names)]], fields=["name", "address_title"])}

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
                    d.receiver_name = address_titles.get(d.receiver_address)
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
        gst_accounts = get_gst_accounts_list(gst_set)
        gst_acc = []
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
        # Creditor or Debtor as a Row in JV Accounts. Batched into one query (was 1 frappe.get_doc() per JV).
        jv_cdn = []
        if jv_list:
            customer_rows = frappe.get_all("Journal Entry Account", filters=[
                ["parent", "in", jv_list], ["parenttype", "=", "Journal Entry"], ["party_type", "=", "Customer"],
            ], fields=["parent"], distinct=True)
            jv_cdn = [row.parent for row in customer_rows]
        cdn_b2b_list = [row.copy() for row in get_rows_from_jv_names(jv_cdn, gst_accounts=gst_accounts)]
        update_child_table(doc=self, table_name="cdn_b2b", row_list=cdn_b2b_list)

    def get_invoices(self, start_date, end_date):
        inv_list = frappe.db.sql("""SELECT name FROM `tabSales Invoice` WHERE docstatus = 1 AND posting_date >= %(start_date)s
        AND posting_date <= %(end_date)s AND company_gstin = %(gstin)s
        ORDER BY customer, name""", {"start_date": start_date, "end_date": end_date, "gstin": self.gstin}, as_dict=1)
        inv_names = [inv.name for inv in inv_list]
        b2b_list, b2cl_list, b2c_list, exp_list, cdn_b2b_list, cdn_b2c_list = [], [], [], [], [], []
        for row in get_rows_from_inv_names(inv_names):
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
        si_tables = GSTR1_SI_TABLES + ["hsn_summary"]
        self.synopsis_text = ""
        for si in si_tables:
            self.set(si, [])


def values_differ(local_val, gst_val, tolerance=0.05):
    # Relative-tolerance comparison, matching the CDN reconciliation check
    # below - int()-truncating before comparing can produce false mismatches
    # near integer boundaries (e.g. 100.99 vs 101.00).
    local_val = flt(local_val)
    gst_val = flt(gst_val)
    if gst_val == 0:
        return abs(local_val) > 0.01
    return abs(local_val - gst_val) / abs(gst_val) > tolerance


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
            if values_differ(taxable, gstin_resp.get("txval")):
                frappe.throw(f"For State Code {gstin_resp.get('pos')} there is a Difference in Taxable Value \
                        GST= {gstin_resp.get('txval')} Our System = {taxable} check rows {str(row_list)}")
            elif values_differ(igst, gstin_resp.get("iamt")):
                frappe.throw(f"For State Code {gstin_resp.get('pos')} there is a Difference in IGST Value \
                        GST= {gstin_resp.get('iamt')} Our System = {igst} check rows {str(row_list)}")
            elif values_differ(sgst, gstin_resp.get("samt")):
                frappe.throw(f"For State Code {gstin_resp.get('pos')} there is a Difference in SGST Value \
                        GST= {gstin_resp.get('samt')} Our System = {sgst} check rows {str(row_list)}")
            elif values_differ(cgst, gstin_resp.get("camt")):
                frappe.throw(f"For State Code {gstin_resp.get('pos')} there is a Difference in CGST Value \
                        GST= {gstin_resp.get('camt')} Our System = {cgst} check rows {str(row_list)}")
            elif values_differ(cess, gstin_resp.get("csamt")):
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
                # Filter out unresolved lookups (None/"" from get_base_doc_frm_docname when the
                # invoice isn't found locally) before building the IN-list - an unfiltered None/""
                # entry silently changes the query's matching semantics instead of raising a clear
                # "invoice not found" error. Unresolved invoices still fall through to the "NO
                # Invoice with Invoice No" throw below via local_rows_by_invoice.get(inv_no, []).
                inv_nos = list({v for v in inv_no_map.values() if v})
                local_rows = []
                if inv_nos:
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


def get_rows_from_jv_names(jv_names, gst_accounts=None):
    # Batched replacement for the old get_row_from_jv_name(jv_name), which did
    # 1 frappe.get_doc("Journal Entry", ...) plus a fresh GST Settings fetch
    # (inside get_taxes_from_jvd) for every single JV. Fetches JV headers and
    # JV Account child rows once for the whole jv_names list instead.
    if not jv_names:
        return []
    if gst_accounts is None:
        gst_accounts = get_gst_accounts_list()
    jv_info = {
        row.name: row for row in frappe.get_all(
            "Journal Entry", filters=[["name", "in", jv_names]],
            fields=["name", "posting_date", "total_debit", "amended_from"])
    }
    account_rows = frappe.get_all("Journal Entry Account", filters=[
        ["parent", "in", jv_names], ["parenttype", "=", "Journal Entry"],
    ], fields=["parent", "account", "party_type", "credit_in_account_currency", "debit_in_account_currency"])
    accounts_by_jv = {}
    for acc in account_rows:
        accounts_by_jv.setdefault(acc.parent, []).append(acc)

    rows = []
    for jv_name in jv_names:
        jv_row = jv_info.get(jv_name)
        if not jv_row:
            frappe.throw(f"Journal Entry {jv_name} Not Found")
        jvd = frappe._dict({"accounts": accounts_by_jv.get(jv_name, [])})
        jv_type = get_gst_jv_type(jvd)
        note_type = "Credit" if jv_type == "credit" else "Debit"
        tax_rate, sgst_amt, cgst_amt, igst_amt, cess_amt, net_amt = get_taxes_from_jvd(
            jvd, jv_type, gst_accounts=gst_accounts)
        row = frappe._dict({})
        row["is_credit_debit"] = 1
        row["note_type"] = note_type
        row["document_type"] = "Journal Entry"
        row["document_number"] = jv_name
        row["invoice_number"] = get_base_doc_no(frappe._dict({
            "doctype": "Journal Entry", "name": jv_name, "amended_from": jv_row.amended_from,
        }))
        row["invoice_date"] = jv_row.posting_date
        row["total_invoice_value"] = jv_row.total_debit
        row["taxable_value"] = net_amt
        row["rate"] = tax_rate
        row["igst"] = igst_amt
        row["sgst"] = sgst_amt
        row["cgst"] = cgst_amt
        rows.append(row)
    return rows


def get_rows_from_inv_names(inv_names):
    # Batched replacement for the old get_row_from_inv_name(inv_name), which
    # did frappe.get_doc() per Sales Invoice, per Address, and (via
    # get_gst_si_type/get_gst_export_fields/get_taxes_from_sid) 2-3 more
    # frappe.get_doc() calls per invoice for the shared GST Settings/Sales
    # Taxes and Charges Template. Fetches everything once for the whole
    # inv_names list, and skips (msgprint, not throw) any invoice with a
    # missing/invalid Customer Address instead of crashing the whole batch.
    if not inv_names:
        return []
    gst_accounts = get_gst_accounts_list()
    si_fields = ["name", "customer_address", "billing_address_gstin", "is_return", "taxes_and_charges",
                 "base_grand_total", "base_net_total", "posting_date", "amended_from",
                 "shipping_bill_number", "shipping_bill_date", "port_code"]
    si_info = {row.name: row for row in frappe.get_all(
        "Sales Invoice", filters=[["name", "in", inv_names]], fields=si_fields)}

    tax_rows = frappe.get_all("Sales Taxes and Charges", filters=[
        ["parent", "in", inv_names], ["parenttype", "=", "Sales Invoice"],
    ], fields=["parent", "account_head", "base_tax_amount", "rate"])
    taxes_by_invoice = {}
    for t in tax_rows:
        taxes_by_invoice.setdefault(t.parent, []).append(t)

    template_names = list({si.taxes_and_charges for si in si_info.values() if si.taxes_and_charges})
    templates = {}
    if template_names:
        templates = {t.name: t for t in frappe.get_all(
            "Sales Taxes and Charges Template", filters=[["name", "in", template_names]],
            fields=["name", "is_export", "export_type"])}

    address_names = list({si.customer_address for si in si_info.values() if si.customer_address})
    addresses = {}
    if address_names:
        addresses = {a.name: a for a in frappe.get_all(
            "Address", filters=[["name", "in", address_names]], fields=["name", "address_title"])}

    rows = []
    for inv_name in inv_names:
        si = si_info.get(inv_name)
        if not si:
            frappe.throw(f"Sales Invoice {inv_name} Not Found")
        if not si.customer_address or si.customer_address not in addresses:
            frappe.msgprint(f"Sales Invoice {inv_name} has No Valid Customer Address - "
                             f"skipped for GSTR1 generation, please correct and re-run")
            continue
        sid = frappe._dict(si)
        sid["doctype"] = "Sales Invoice"
        sid["taxes"] = taxes_by_invoice.get(inv_name, [])
        tax_template = templates.get(si.taxes_and_charges)
        multi_factor = 1
        row = frappe._dict({})
        inv_type = get_gst_si_type(sid, tax_template=tax_template)
        if inv_type == "cdn_b2b" or inv_type == "cdn_b2c":
            row["is_credit_debit"] = 1
            row["note_type"] = "Credit"
            multi_factor = -1
        elif inv_type == "export":
            row["export_sales"] = 1
            row["shipping_bill_no"], row["shipping_bill_date"], row["gst_payment"], row["port_code"] = \
                get_gst_export_fields(sid, tax_template=tax_template)
        base_inv_no = get_base_doc_no(sid)
        tax_rate, sgst_amt, cgst_amt, igst_amt, cess_amt = get_taxes_from_sid(sid, gst_accounts=gst_accounts)
        row["invoice_type_2"] = inv_type
        row["invoice_type"] = "R-Regular B2B Invoices" # TODO make invoice Type dynamic instead of static
        row["receiver_address"] = si.customer_address
        row["receiver_gstin"] = si.billing_address_gstin
        row["document_type"] = "Sales Invoice"
        row["document_number"] = si.name
        row["invoice_number"] = base_inv_no
        row["receiver_name"] = addresses[si.customer_address].address_title
        row["invoice_date"] = si.posting_date
        row["total_invoice_value"] = si.base_grand_total * multi_factor
        row["rate"] = tax_rate
        row["taxable_value"] = si.base_net_total * multi_factor
        row["igst"] = igst_amt * multi_factor
        row["sgst"] = sgst_amt * multi_factor
        row["cgst"] = cgst_amt * multi_factor
        rows.append(row)
    return rows

def correct_invoice_gst_as_per_gstr1(inv_no, corr_gstin):
    frappe.db.set_value("Sales Invoice", inv_no, "billing_address_gstin", corr_gstin)
    frappe.msgprint(f"Corrected SI# {inv_no} with Correct GSTIN {corr_gstin}")
    sid = frappe.get_doc("Sales Invoice", inv_no)
    if sid.amended_from:
        correct_invoice_gst_as_per_gstr1(inv_no=sid.amended_from, corr_gstin=corr_gstin)

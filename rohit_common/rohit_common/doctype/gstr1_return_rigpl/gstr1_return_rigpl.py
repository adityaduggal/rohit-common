# -*- coding: utf-8 -*-
# Copyright (c) 2021, Rohit Industries Ltd. and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
import json
from datetime import datetime
from frappe.model.document import Document
from frappe.utils import cint, getdate, flt
from frappe.utils.background_jobs import get_jobs
from erpnext.accounts.utils import get_fiscal_year
from ....utils.common import update_child_table
from ....utils.accounts_utils import get_gst_accounts, get_si_taxes_map, gst_si_type, export_fields, \
    gst_jv_type, taxes_from_jv_accounts, get_jv_party_map, get_party_addresses, pick_address, \
    get_hsn_summary_for_invoices, get_inv_status, get_invoice_uploader, get_base_doc_map
from ...india_gst_api.common import gst_return_period_validation, get_dates_from_return_period
from ...india_gst_api.gst_api import get_gstr1
from ...india_gst_api.gst_public_api import track_return_whitebooks, get_arn_status

SI_TABLES = ["b2b_invoices", "b2cl_invoices", "cdn_b2c", "cdn_b2b", "export_invoices", "b2c_invoices"]

# WhiteBooks path segment: (response key, local table, name). These sections are reconciled row by row.
RECONCILED_SECTIONS = {
    "b2b": ("b2b", "b2b_invoices", "B2B"),
    "b2cl": ("b2cl", "b2cl_invoices", "B2C Large"),
    "b2cs": ("b2cs", "b2c_invoices", "B2C Small"),
    "cdnr": ("cdnr", "cdn_b2b", "CDN Registered"),
    "cdnur": ("cdnur", "cdn_b2c", "CDN Un-Registered"),
    "exp": ("exp", "export_invoices", "Export Invoices"),
    # Amendments of invoices reported in earlier periods. Their rows are entered by hand (nothing fills them
    # from Sales Invoices yet), so they are not in SI_TABLES: get_details() keeps them, and they are not in
    # the HSN summary of this period.
    "b2ba": ("b2ba", "b2ba_invoices", "B2B Amendments"),
    "b2cla": ("b2cla", "b2cla_invoices", "B2C Large Amendments"),
    "b2csa": ("b2csa", "b2csa_invoices", "B2C Small Amendments"),
    "cdnra": ("cdnra", "cdb_b2ba", "CDN Registered Amendments"),
    "cdnura": ("cdnura", "cdn_b2ca", "CDN Un-Registered Amendments"),
    "expa": ("expa", "export_amend", "Export Invoices Amendments"),
}
AMENDMENT_TABLES = ["b2ba_invoices", "b2cla_invoices", "b2csa_invoices", "cdb_b2ba", "cdn_b2ca", "export_amend"]
B2CS_SECTIONS = ("b2cs", "b2csa")
# Rupees. GSTN B2CS totals are rounded, so paise-level differences are not mismatches.
B2CS_TOLERANCE = 1.0
# This doctype has no table for these sections, so GST data in any of them means the return can't be
# reconciled here.
UNRECONCILED_SECTIONS = {
    "at": ("at", "Advances Tax"),
    "ata": ("ata", "Advances Tax Amendments"),
    "txp": ("txpd", "Tax Paid"),
    "txpa": ("txpda", "Tax Paid Amendments"),
}

# {"action": "RETSTATUS", "name": "GSTR1 Status", "tbl": "none"}
# {"action": "RETSUM", "name": "GSTR1 Summary", "tbl": "none"}
# {"action": "RETSUBMIT", "name": "Submit GSTR1", "tbl": "none"}
# {"action": "RESET", "name": "Reset GSTR1"}
# {"action": "RESTSAVE", "name": "Save GSTR1"}


class GSTR1ReturnRIGPL(Document):

    @frappe.whitelist()
    def get_gstr1_details(self):
        if self.is_new() == 1:
            frappe.throw("Save the document before Getting GSTR1 Data")
        self.check_permission("write")
        if not self.arn_number:
            # If GSTR1 is not Filed then Check if Filed and if Filed then get the ARN and other details and verify
            # from GST Network
            first_date_text = self.return_period[2:] + "-" + self.return_period[:2] + "-" + "01"
            fy = get_fiscal_year(date=getdate(first_date_text))  # format for getdate is YYYY-MM-DD
            return_status = track_return_whitebooks(gstin=self.gstin, fiscal_year=fy[0], type_of_return="R1")
            self.arn_number, self.filing_status, self.filing_date, self.mode_of_filing = \
                get_arn_status(ret_status_json=return_status, type_of_return="GSTR1", ret_period=self.return_period)
            if not self.arn_number:
                self.filing_status = "Not Filed"
                frappe.msgprint(f"{self.name} is Not Filed on GST Portal we can file it from here")
            else:
                self.save()
        else:
            # If GSTR1 arn is there then verify the data with generated GSTR1 with ERP and GSTR Network.
            # About 16 API calls, so it runs in the background.
            job_name = f"gstr1-reconcile-{self.name}"
            if job_name in get_jobs(site=frappe.local.site, key="job_name").get(frappe.local.site, []):
                frappe.throw(f"GSTR1 reconciliation for {self.name} is already queued or running",
                             title="GSTR1 Reconciliation Already Running")
            frappe.enqueue("rohit_common.rohit_common.doctype.gstr1_return_rigpl.gstr1_return_rigpl."
                           "reconcile_gstr1_job", queue="long", timeout=1500, job_name=job_name,
                           docname=self.name)
            frappe.msgprint(f"GSTR1 for {self.return_period} is being fetched from the GST Network. You will get a "
                            "message when it is done. Reconciliation uses the saved version of this document.")

    def apply_gst_network_data(self, gst_data):
        """
        Reconciles the downloaded GSTR1 sections with the child tables in memory. Returns a list of errors.
        Rows are changed only if there are no errors, so a failed reconciliation changes nothing.
        """
        errors = []
        for path, (_, name) in UNRECONCILED_SECTIONS.items():
            if gst_data.get(path):
                errors.append(f"<b>{name}</b>: GST Network has {len(gst_data[path])} entries but this document "
                              "has no table for them")

        rows_by_tbl = {tbl: self.get(tbl) or [] for tbl in SI_TABLES + AMENDMENT_TABLES}
        doc_nos = collect_gst_document_numbers(gst_data)
        base_maps = {"Sales Invoice": get_base_doc_map("Sales Invoice", doc_nos)}
        if any(d.document_type == "Journal Entry" for rows in rows_by_tbl.values() for d in rows):
            base_maps["Journal Entry"] = get_base_doc_map("Journal Entry", doc_nos)
        state_codes = get_state_codes([d.receiver_address for tbl in ("b2c_invoices", "b2csa_invoices")
                                       for d in rows_by_tbl[tbl]])

        updates = {}
        for path, (_, tbl, name) in RECONCILED_SECTIONS.items():
            entries = gst_data.get(path) or []
            local_rows = rows_by_tbl[tbl]
            if not local_rows and entries:
                errors.append(f"For <b>{name}</b> there is Data in GST Network but Table for the Same is Empty")
            elif local_rows and not entries:
                errors.append(f"For <b>{name}</b> there is No Data in GST Network but Table for the Same has Data")
            elif path in B2CS_SECTIONS:
                match_b2cs(entries, local_rows, state_codes, updates, errors)
            else:
                for entry in entries:
                    match_gst_entry(frappe._dict(entry), local_rows, base_maps, updates, errors)

        if not errors:
            for rows in rows_by_tbl.values():
                for row in rows:
                    if row.name in updates:
                        row.update(updates[row.name])
        return errors

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
        si_names = [row.document_number for tbl in SI_TABLES for row in self.get(tbl) or []
                    if row.document_type == "Sales Invoice"]
        update_child_table(doc=self, table_name="hsn_summary", row_list=get_hsn_summary_for_invoices(si_names))

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
        self.update_receiver_details()
        tbls_fully_validated = 0
        empty_tables = 0
        if self.filing_status == "Filed":
            filed = 1
        else:
            filed = 0
        for tbl in SI_TABLES:
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
                if no_chk_rows > 0:
                    message = f"There are {no_chk_rows} rows in Table: {tbl} where GSTIN Checksum is missing But since return is filed \
                    you wont be able to Submit the Document. Pull the Data from GSTIN Network to Submit."
                    if no_chk_rows != len(row_list):
                        message += f" The rows are {str(row_list)}"
                    if submit == 1:
                        frappe.throw(message)
                    elif filed == 1:
                        frappe.msgprint(message)
                else:
                    tbls_fully_validated += 1
        if tbls_fully_validated == len(SI_TABLES) - empty_tables and tbls_fully_validated > 0:
            frappe.msgprint(f"GSTR1 Return: {self.name} is now Fully validated and Can be Submitted")
            self.fully_validated = 1
        else:
            self.fully_validated = 0

    def update_receiver_details(self):
        """
        Sets receiver address, GSTIN and name on every row from its Sales Invoice, or for a Journal Entry from
        the party's address. Constant number of queries for any number of rows.
        """
        rows = [d for tbl in SI_TABLES for d in self.get(tbl) or []]
        for d in rows:
            if d.document_type not in ("Sales Invoice", "Journal Entry"):
                frappe.throw(f"{d.document_type} mentioned in Row# {d.idx} is Not Supported")
        si_names = [d.document_number for d in rows if d.document_type == "Sales Invoice"]
        jv_names = [d.document_number for d in rows if d.document_type == "Journal Entry"]
        si_map = {}
        if si_names:
            si_map = {si.name: si for si in frappe.get_all(
                "Sales Invoice", filters={"name": ["in", si_names]},
                fields=["name", "customer_address", "billing_address_gstin"])}
        jv_party = get_jv_party_map(jv_names)
        party_addresses = get_party_addresses(jv_party.values())

        for d in rows:
            if d.document_type == "Sales Invoice":
                si = si_map.get(d.document_number)
                if not si:
                    frappe.throw(f"Sales Invoice {d.document_number} in Row# {d.idx} does not exist")
                d.receiver_address = si.customer_address
                d.receiver_gstin = si.billing_address_gstin
            else:
                link_dt, link_dn = jv_party.get(d.document_number, ("", ""))
                addresses = party_addresses.get((link_dt, link_dn), [])
                # Once the linked Party is obtained we can automatically fill the address by guess
                if not d.receiver_address:
                    d.receiver_address = pick_address(addresses, link_dt, link_dn)
                if d.receiver_address not in {a.name for a in addresses}:
                    frappe.throw(f"Address {d.receiver_address} does not belong to {link_dt} {link_dn}")

        address_map = {}
        receiver_addresses = list({d.receiver_address for d in rows if d.receiver_address})
        if receiver_addresses:
            address_map = {a.name: a for a in frappe.get_all(
                "Address", filters={"name": ["in", receiver_addresses]}, fields=["name", "gstin", "address_title"])}
        for d in rows:
            address = address_map.get(d.receiver_address) or frappe._dict()
            if d.document_type == "Journal Entry":
                d.receiver_gstin = address.gstin
            d.receiver_name = address.address_title

    def validate_export_invoices(self):
        for d in self.export_invoices:
            if not d.gst_payment or not d.port_code or not d.shipping_bill_no or not d.shipping_bill_date:
                frappe.throw(f"For Row# {d.idx} in Export Invoices either GST Payment or Port Code or SHB Details "
                             f"are not mentioned.")

    @frappe.whitelist()
    def get_details(self):
        self.check_permission("write")
        self.clear_all_tables()
        self.generate_gstr1()
        self.save()

    def generate_gstr1(self):
        frm_dt, to_dt = get_dates_from_return_period(self.return_period)
        gst_accounts = get_gst_accounts()
        self.get_invoices(start_date=frm_dt, end_date=to_dt, gst_accounts=gst_accounts)
        self.get_jv_entries(start_date=frm_dt, end_date=to_dt, gst_accounts=gst_accounts)
        frappe.msgprint("Updated All Tables")

    def get_jv_entries(self, start_date, end_date, gst_accounts):
        gst_acc = {acc for row in gst_accounts for acc in row.values() if acc}
        jv = frappe.qb.DocType("Journal Entry")
        jva = frappe.qb.DocType("Journal Entry Account")
        jv_rows = (
            frappe.qb.from_(jv).join(jva).on(jva.parent == jv.name)
            .select(jv.name, jv.posting_date, jv.total_debit, jv.amended_from, jva.account, jva.party_type,
                    jva.party, jva.debit_in_account_currency, jva.credit_in_account_currency)
            .where((jv.docstatus == 1) & (jv.posting_date >= start_date) & (jv.posting_date <= end_date)
                   & (jva.parenttype == "Journal Entry") & (jva.parentfield == "accounts"))
            .orderby(jv.posting_date).orderby(jv.name).orderby(jva.idx)
            .run(as_dict=True)
        )
        accounts_by_jv = {}
        for row in jv_rows:
            accounts_by_jv.setdefault(row.name, []).append(row)
        # JV in period where GST Accounts are there. Now JV would be Credit or Debit if it has
        # Creditor or Debtor as a Row in JV Accounts
        jv_cdn = [name for name, accounts in accounts_by_jv.items()
                  if any(acc.account in gst_acc for acc in accounts)
                  and any(acc.party_type == "Customer" for acc in accounts)]
        base_map = get_base_doc_map("Journal Entry", jv_cdn)
        cdn_b2b_list = []
        for name in jv_cdn:
            if name not in base_map:
                frappe.throw(f"Amendment chain of Journal Entry {name} is broken")
            cdn_b2b_list.append(build_row_from_jv(accounts_by_jv[name], base_map[name], gst_accounts))
        update_child_table(doc=self, table_name="cdn_b2b", row_list=cdn_b2b_list)

    def get_invoices(self, start_date, end_date, gst_accounts):
        invoices = frappe.get_all(
            "Sales Invoice",
            filters={"docstatus": 1, "posting_date": ["between", [start_date, end_date]],
                     "company_gstin": self.gstin},
            fields=["name", "is_return", "billing_address_gstin", "base_grand_total", "base_net_total",
                    "taxes_and_charges", "shipping_bill_number", "shipping_bill_date", "port_code",
                    "customer_address", "posting_date"],
            order_by="customer, name")
        if not invoices:
            return
        for si in invoices:
            if not si.taxes_and_charges:
                frappe.throw(f"Sales Taxes and Charges Template is not set in Sales Invoice {si.name}")
        si_names = [si.name for si in invoices]
        templates = {t.name: t for t in frappe.get_all(
            "Sales Taxes and Charges Template", filters={"name": ["in", list({si.taxes_and_charges for si in invoices})]},
            fields=["name", "is_export", "export_type"])}
        address_titles = {a.name: a.address_title for a in frappe.get_all(
            "Address", filters={"name": ["in", list({si.customer_address for si in invoices if si.customer_address})]},
            fields=["name", "address_title"])}
        base_map = get_base_doc_map("Sales Invoice", si_names)
        taxes_by_si = get_si_taxes_map(si_names, gst_accounts)

        rows_by_type = {"b2b": [], "b2cl": [], "b2c": [], "export": [], "cdn_b2c": [], "cdn_b2b": []}
        for si in invoices:
            if si.customer_address not in address_titles:
                frappe.throw(f"Customer Address {si.customer_address} of Sales Invoice {si.name} does not exist")
            if si.name not in base_map:
                frappe.throw(f"Amendment chain of Sales Invoice {si.name} is broken")
            row = build_row_from_si(si, templates[si.taxes_and_charges], address_titles[si.customer_address],
                                    base_map[si.name], taxes_by_si[si.name])
            if row["invoice_type_2"] not in rows_by_type:
                frappe.throw(f"Unknown Invoice Type for {row.document_number}")
            rows_by_type[row["invoice_type_2"]].append(row)
        update_child_table(doc=self, table_name="b2b_invoices", row_list=rows_by_type["b2b"])
        update_child_table(doc=self, table_name="b2cl_invoices", row_list=rows_by_type["b2cl"])
        update_child_table(doc=self, table_name="b2c_invoices", row_list=rows_by_type["b2c"])
        update_child_table(doc=self, table_name="export_invoices", row_list=rows_by_type["export"])
        update_child_table(doc=self, table_name="cdn_b2b", row_list=rows_by_type["cdn_b2b"])
        update_child_table(doc=self, table_name="cdn_b2c", row_list=rows_by_type["cdn_b2c"])

    @frappe.whitelist()
    def clear_all_tables(self):
        self.check_permission("write")
        self.synopsis_text = ""
        for si in SI_TABLES + ["hsn_summary"]:
            self.set(si, [])


def reconcile_gstr1_job(docname):
    """
    Background job: downloads GSTR1 from the GST Network and reconciles it with the document. All sections
    are fetched before anything is changed, and the document is saved once, only if every section matches.
    """
    doc = frappe.get_doc("GSTR1 Return RIGPL", docname)
    sections = {path: key for path, (key, _, _) in RECONCILED_SECTIONS.items()}
    sections.update({path: key for path, (key, _) in UNRECONCILED_SECTIONS.items()})
    try:
        gst_data = get_gstr1(gstin=doc.gstin, ret_period=doc.return_period, sections=sections)
        doc.json_reply = json.dumps(gst_data, default=str)
        errors = doc.apply_gst_network_data(gst_data)
        if errors:
            frappe.db.rollback()
            # Keep the raw reply so the mismatches can be checked against it.
            frappe.db.set_value(doc.doctype, doc.name, "json_reply", doc.json_reply, update_modified=False)
            _notify(f"GSTR1 {doc.name} does not match the GST Network. Nothing was changed.<br><br>"
                    + "<br>".join(errors), title="GSTR1 Reconciliation Failed", indicator="red")
            return
        doc.save()
        _notify(f"GSTR1 {doc.name} for {doc.return_period} is fetched and reconciled with the GST Network",
                title="GSTR1 Reconciled", indicator="green")
    except Exception:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), f"GSTR1 Reconciliation Failed for {docname}")
        _notify(f"GSTR1 reconciliation for {docname} failed: {frappe.get_traceback().splitlines()[-1]}. "
                "See Error Log for details.", title="GSTR1 Reconciliation Failed", indicator="red")


def _notify(message, title, indicator):
    frappe.publish_realtime("msgprint", {"message": message, "title": title, "indicator": indicator},
                            user=frappe.session.user)


def collect_gst_document_numbers(gst_data):
    """Every invoice/note number in the downloaded sections."""
    numbers = set()
    for path in RECONCILED_SECTIONS:
        for entry in gst_data.get(path) or []:
            for doc in (entry.get("inv") or entry.get("nt") or [entry]):
                if doc.get("inum") or doc.get("nt_num"):
                    numbers.add(doc.get("inum") or doc.get("nt_num"))
    return list(numbers)


def get_state_codes(addresses):
    """{Address: numeric state code} in one query."""
    addresses = list({a for a in addresses if a})
    if not addresses:
        return {}
    ad = frappe.qb.DocType("Address")
    st = frappe.qb.DocType("State")
    rows = (frappe.qb.from_(ad).join(st).on(st.name == ad.state_rigpl)
            .select(ad.name, st.state_code_numeric).where(ad.name.isin(addresses)).run(as_dict=True))
    return {row.name: cint(row.state_code_numeric) for row in rows}


def match_b2cs(entries, local_rows, state_codes, updates, errors):
    """
    GST Network reports B2C Small supplies per place of supply (and per rate and supply type), so the
    rows of each state are compared with the total of all GST entries for that state.
    """
    gst_by_state = {}
    for entry in entries:
        pos = cint(entry.get("pos"))
        totals = gst_by_state.setdefault(pos, {"txval": 0, "iamt": 0, "samt": 0, "camt": 0, "csamt": 0,
                                               "flag": entry.get("flag"), "chksum": entry.get("chksum")})
        # B2CSA entries keep the amounts per rate in itms; B2CS entries have them at the top level.
        for amounts in entry.get("itms") or [entry]:
            for key in ("txval", "iamt", "samt", "camt", "csamt"):
                totals[key] += flt(amounts.get(key))
    for pos, gst in gst_by_state.items():
        si_state_wise = [d for d in local_rows if state_codes.get(d.receiver_address) == pos]
        if not si_state_wise:
            errors.append(f"There is No Data for State Code = {pos} in our System whereas in GSTIN There is for "
                          "B2C Small")
            continue
        row_list = [d.idx for d in si_state_wise]
        ours = {
            "txval": sum(flt(d.taxable_value) for d in si_state_wise),
            "iamt": sum(flt(d.igst) for d in si_state_wise),
            "samt": sum(flt(d.sgst) for d in si_state_wise),
            "camt": sum(flt(d.cgst) for d in si_state_wise),
            "csamt": sum(flt(d.cess) for d in si_state_wise),
        }
        mismatched = False
        for key, label in (("txval", "Taxable"), ("iamt", "IGST"), ("samt", "SGST"), ("camt", "CGST"),
                           ("csamt", "Cess")):
            if abs(ours[key] - gst[key]) > B2CS_TOLERANCE:
                errors.append(f"For State Code {pos} there is a Difference in {label} Value "
                              f"GST= {gst[key]} Our System = {ours[key]} check rows {str(row_list)}")
                mismatched = True
                break
        if not mismatched:
            for d in si_state_wise:
                updates[d.name] = {"invoice_status": get_inv_status(gst["flag"]), "invoice_checksum": gst["chksum"]}


def match_gst_entry(gstin_resp, local_rows, base_maps, updates, errors):
    """One GST Network entry: a receiver GSTIN with its invoices/notes (B2B, CDNR), a place of supply or export
    type with its invoices (B2CL, EXP), or a single note (CDNUR)."""
    gst_docs = gstin_resp.get("nt") or gstin_resp.get("inv") or [gstin_resp]
    si_gstin = [d for d in local_rows if gstin_resp.ctin and d.receiver_gstin == gstin_resp.ctin]
    if si_gstin:
        if len(si_gstin) != len(gst_docs):
            errors.append(f"For GSTIN: {gstin_resp.ctin} Total Invoices in GST= {len(gst_docs)} Whereas in "
                          f"System the Total Invoices = {len(si_gstin)}")
            return
        for gst_doc in gst_docs:
            check_invoice_integrity(gst_doc, si_gstin, base_maps, updates, errors)
        return
    # GSTIN is not found (or the section has none) so search by the invoice number of the GST Network
    for gst_doc in gst_docs:
        doc_no = gst_doc.get("inum") or gst_doc.get("nt_num")
        if not doc_no:
            errors.append(f"For GSTIN: {gstin_resp.ctin} No Linked Invoices Found")
            continue
        base_no = base_maps["Sales Invoice"].get(doc_no, "")
        si_from_si_no = [d for d in local_rows if base_no and d.invoice_number == base_no]
        if not si_from_si_no and "Journal Entry" in base_maps:
            jv_base_no = base_maps["Journal Entry"].get(doc_no, "")
            si_from_si_no = [d for d in local_rows if jv_base_no and d.invoice_number == jv_base_no]
        if si_from_si_no:
            check_invoice_integrity(gst_doc, si_from_si_no, base_maps, updates, errors)
        else:
            errors.append(f"For GSTIN: {gstin_resp.ctin} there is NO Invoice with Invoice No {doc_no} in Our System")


def check_invoice_integrity(gst_inv_data, local_inv_data, base_maps, updates, errors):
    inv = gst_inv_data
    inv_found = 0
    for row in local_inv_data:
        base_map = base_maps.get(row.document_type, {})
        if inv.get("sbnum"):
            # Case of Export Invoices
            base_doc_no = base_map.get(inv.get("inum"), "")
            if inv.get("sbnum") == row.shipping_bill_no or base_doc_no == row.invoice_number:
                inv_found = 1
                gst_shb_date = datetime.strptime(inv.get("sbdt"), "%d-%m-%Y").date()
                if gst_shb_date != getdate(row.shipping_bill_date):
                    errors.append(f"For Row# {row.idx} SHB Date on GST = {gst_shb_date} whereas in System its "
                                  f"{row.shipping_bill_date}")
                elif flt(inv.get("val"), 2) != flt(row.total_invoice_value, 2):
                    errors.append(f"For Row# {row.idx} Total Invoice Value {row.total_invoice_value} does "
                                  f"not Match with GST Network Inv Value <b>{inv.get('val')}</b>")
                else:
                    updates[row.name] = {"invoice_status": get_inv_status(inv.get('flag')),
                                         "invoice_checksum": inv.get("chksum")}
        elif inv.get("nt_num"):
            # Case of Credit and Debit Notes
            base_doc_no = base_map.get(inv.get("nt_num"), "")
            if base_doc_no == row.invoice_number:
                inv_found = 1
                gst_inv_date = datetime.strptime(inv.get("nt_dt"), "%d-%m-%Y").date()
                gst_val = flt(inv.get("val"))
                if not gst_val or abs(gst_val - flt(row.total_invoice_value)) / abs(gst_val) > 0.05:
                    errors.append(f"For Row# {row.idx} Total Invoice Value {row.total_invoice_value} does "
                                  f"not Match with GST Network Inv Value <b>{inv.get('val')}</b>")
                elif gst_inv_date != getdate(row.invoice_date):
                    errors.append(f"For Row# {row.idx} Invoice Date {row.invoice_date} does not Match with GST "
                                  f"Network Inv Date <b>{gst_inv_date}</b>")
                else:
                    updates[row.name] = {"invoice_status": get_inv_status(inv.get('flag')),
                                         "uploaded_by": get_invoice_uploader(inv.get('updby')),
                                         "invoice_checksum": inv.get("chksum")}
        else:
            base_doc_no = base_map.get(inv.get("inum"), "")
            if base_doc_no == row.invoice_number:
                inv_found = 1
                gst_inv_date = datetime.strptime(inv.get("idt"), "%d-%m-%Y").date()
                if flt(inv.get("val"), 2) != flt(row.total_invoice_value, 2):
                    errors.append(f"For Row# {row.idx} Total Invoice Value {row.total_invoice_value} does "
                                  f"not Match with GST Network Inv Value <b>{inv.get('val')}</b>")
                elif gst_inv_date != getdate(row.invoice_date):
                    errors.append(f"For Row# {row.idx} Invoice Date {row.invoice_date} does not Match with GST "
                                  f"Network Inv Date <b>{gst_inv_date}</b>")
                else:
                    updates[row.name] = {"invoice_status": get_inv_status(inv.get('flag')),
                                         "uploaded_by": get_invoice_uploader(inv.get('updby')),
                                         "invoice_checksum": inv.get("chksum")}
    if inv_found != 1:
        inv_no = inv.get("nt_num") or inv.get("inum")
        errors.append(f"Document {inv_no} of the GST Network is Not Found in this document")


def build_row_from_jv(jv_accounts, base_no, gst_accounts):
    """GSTR1 row for a Journal Entry from its account rows (as fetched by get_jv_entries)."""
    jvd = jv_accounts[0]
    jv_type = gst_jv_type(jv_accounts)
    if jv_type == "credit":
        note_type = "Credit"
    else:
        note_type = "Debit"
    tax_rate, sgst_amt, cgst_amt, igst_amt, cess_amt, net_amt = taxes_from_jv_accounts(jv_accounts, jv_type,
                                                                                       gst_accounts)
    row = frappe._dict({})
    row["is_credit_debit"] = 1
    row["note_type"] = note_type
    row["document_type"] = "Journal Entry"
    row["document_number"] = jvd.name
    row["invoice_number"] = base_no
    row["invoice_date"] = jvd.posting_date
    row["total_invoice_value"] = jvd.total_debit
    row["taxable_value"] = net_amt
    row["rate"] = tax_rate
    row["igst"] = igst_amt
    row["sgst"] = sgst_amt
    row["cgst"] = cgst_amt
    return row


def build_row_from_si(si, template, address_title, base_inv_no, taxes):
    """GSTR1 row for a Sales Invoice. taxes is (tax_rate, sgst, cgst, igst, cess) from get_si_taxes_map()."""
    row = frappe._dict({})
    multi_factor = 1
    inv_type = gst_si_type(si, template.is_export)
    if inv_type == "cdn_b2b" or inv_type == "cdn_b2c":
        row["is_credit_debit"] = 1
        row["note_type"] = "Credit"
        multi_factor = -1
    elif inv_type == "export":
        row["export_sales"] = 1
        row["shipping_bill_no"], row["shipping_bill_date"], row["gst_payment"], row["port_code"] = \
            export_fields(si, template)
    tax_rate, sgst_amt, cgst_amt, igst_amt, cess_amt = taxes
    row["invoice_type_2"] = inv_type
    row["invoice_type"] = "R-Regular B2B Invoices"  # TODO make invoice Type dynamic instead of static
    row["receiver_address"] = si.customer_address
    row["receiver_gstin"] = si.billing_address_gstin
    row["document_type"] = "Sales Invoice"
    row["document_number"] = si.name
    row["invoice_number"] = base_inv_no
    row["receiver_name"] = address_title
    row["invoice_date"] = si.posting_date
    row["total_invoice_value"] = si.base_grand_total * multi_factor
    row["rate"] = tax_rate
    row["taxable_value"] = si.base_net_total * multi_factor
    row["igst"] = igst_amt * multi_factor
    row["sgst"] = sgst_amt * multi_factor
    row["cgst"] = cgst_amt * multi_factor
    return row


def correct_invoice_gst_as_per_gstr1(inv_no, corr_gstin):
    frappe.db.set_value("Sales Invoice", inv_no, "billing_address_gstin", corr_gstin)
    frappe.msgprint(f"Corrected SI# {inv_no} with Correct GSTIN {corr_gstin}")
    amended_from = frappe.db.get_value("Sales Invoice", inv_no, "amended_from")
    if amended_from:
        correct_invoice_gst_as_per_gstr1(inv_no=amended_from, corr_gstin=corr_gstin)

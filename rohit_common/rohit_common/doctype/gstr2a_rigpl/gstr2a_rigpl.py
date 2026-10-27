# Copyright (c) 2021, Rohit Industries Ltd. and contributors
# For license information, please see license.txt
# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import frappe
from datetime import datetime
from frappe.utils import flt
from frappe.utils.background_jobs import get_jobs
from ...india_gst_api.common import gst_return_period_validation, validate_gstin
from ...india_gst_api.gst_api import get_invoice_type, get_type_of_amend, get_gstr2a, get_gstr2b
from frappe.model.document import Document

# WhiteBooks path segment: (response key, name)
GSTR2A_SECTIONS = {
    "b2b": ("b2b", "B2B"),
    "b2ba": ("b2ba", "B2B Amendments"),
    "cdn": ("cdn", "Credit or Debit Notes"),
    "cdna": ("cdna", "Credit or Debit Note Amendments"),
    "impg": ("impg", "Import Data"),
    "impgsez": ("impgsez", "Imports from SEZ"),
    "isd": ("isd", "Input Service Distributer"),
    "tcs": ("tcs", "Tax Collected at Source"),
    "tds": ("tds", "Tax Deducted at Source"),
}


class GSTR2ARIGPL(Document):

    @frappe.whitelist()
    def reset_matching(self):
        self.check_permission("write")
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

    @frappe.whitelist()
    def clear_table(self):
        self.check_permission("write")
        self.invoices = []
        self.gstr2b_gen_date = ""
        self.filed_taxable_value = 0
        self.filed_tax_amount = 0
        self.matched_taxable_value = 0
        self.total_taxable_value = 0
        self.unfiled_tax_amount = 0
        self.unfiled_taxable_value = 0
        self.unmatched_taxable_value = 0

    @frappe.whitelist()
    def get_gstr2a_data(self):
        if self.is_new() == 1:
            frappe.throw("Save the document before Getting GSTR2A Data")
        if self.disable_gst_update == 1:
            frappe.throw("GST Network Update is Disabled. Uncheck Disable GST Update to update from GST. Also note"
                         "Updating from GST Network would remove all manual remarks and linking")
        self.check_permission("write")
        # 9 API calls, so it runs in the background.
        job_name = f"gstr2a-fetch-{self.name}"
        if job_name in get_jobs(site=frappe.local.site, key="job_name").get(frappe.local.site, []):
            frappe.throw(f"GSTR2A update for {self.name} is already queued or running",
                         title="GSTR2A Update Already Running")
        frappe.enqueue("rohit_common.rohit_common.doctype.gstr2a_rigpl.gstr2a_rigpl.fetch_gstr2a_job",
                       queue="long", timeout=1500, job_name=job_name, docname=self.name)
        frappe.msgprint(f"GSTR2A for {self.return_period} is being fetched from the GST Network. You will get a "
                        "message when it is done.")

    def update_from_gst_network(self, gst_data):
        """Replaces the invoices table with the downloaded GSTR2A sections."""
        self.clear_table()
        for path, (key, _) in GSTR2A_SECTIONS.items():
            if gst_data.get(path):
                self.create_new_table(gst_data[path])

    @frappe.whitelist()
    def get_gstr2b_data(self):
        if self.gstr2b_gen_date:
            frappe.throw(f"GSTR2B Already Generated on {self.gstr2b_gen_date}")
        self.check_permission("write")
        resp = get_gstr2b(gstin=self.gstin, ret_period=self.return_period)
        self.process_gstr2b_response(response=resp)
        # The rows were updated in the DB, so send the saved version back to the form.
        self.reload()

    def process_gstr2b_response(self, response):
        """
        Marks every GSTR2 Return Invoices row found in GSTR2B with the GSTR2B date and period. All rows are
        matched first, with one query, and updated with one query, only if every GSTR2B document is found.
        """
        data = response.get("data")
        gstr2b_date = datetime.strptime(data.get("gendt"), "%d-%m-%Y").date()
        data_lists = ["b2b", "b2ba", "cdnr", "cdnra", "isd", "isda", "impg", "impgsez"]
        docs = data.get("docdata") or {}
        # (section, supplier GSTIN, supplier period, document number); GSTIN and period are None for impg
        wanted = []
        for dt in data_lists:
            for row in docs.get(dt) or []:
                if dt == "cdnr":
                    invoices, inv_no_field = row.get("nt"), "ntnum"
                elif dt == "impg":
                    invoices, inv_no_field = [row], "boenum"
                else:
                    invoices, inv_no_field = row.get("inv"), "inum"
                for inv in invoices or []:
                    if dt == "impg":
                        wanted.append((dt, None, None, inv.get(inv_no_field)))
                    else:
                        wanted.append((dt, row.get("ctin"), row.get("supprd"), inv.get(inv_no_field)))
        if not wanted:
            frappe.msgprint("GSTR2B has no documents")
            return

        g2 = frappe.qb.DocType("GSTR2A RIGPL")
        gi = frappe.qb.DocType("GSTR2 Return Invoices")
        gstr2_rows = (
            frappe.qb.from_(g2).join(gi).on(gi.parent == g2.name)
            .select(gi.name, gi.supplier_invoice_no, gi.party_gstin, g2.return_period)
            .where((gi.parenttype == "GSTR2A RIGPL") & (gi.parentfield == "invoices") & gi.supplier_invoice_no.isin(list({w[3] for w in wanted})))
            .run(as_dict=True)
        )
        rows_by_invoice_no = {}
        for r in gstr2_rows:
            rows_by_invoice_no.setdefault(r.supplier_invoice_no, []).append(r)

        row_names, missing = set(), []
        for dt, ctin, supprd, inv_no in wanted:
            matched = [r for r in rows_by_invoice_no.get(inv_no, [])
                       if dt == "impg" or (r.party_gstin == ctin and r.return_period == supprd)]
            if not matched:
                missing.append(f"{dt.upper()} {inv_no} of GSTIN {ctin} for period {supprd}")
            row_names.update(m.name for m in matched)
        if missing:
            frappe.throw("No GSTR2 Data found for these GSTR2B documents:<br>" + "<br>".join(missing),
                         title="GSTR2B Documents Not in GSTR2A")

        frappe.db.set_value(self.doctype, self.name, "gstr2b_gen_date", gstr2b_date)
        frappe.qb.update(gi).set(gi.gstr2b_date, gstr2b_date).set(gi.gstr2b_period, self.return_period).set(
            gi.modified, frappe.utils.now()).set(gi.modified_by, frappe.session.user).where(
            gi.name.isin(list(row_names))).run()
        frappe.msgprint(f"GSTR2B dated {gstr2b_date} is updated in {len(row_names)} rows")

    @frappe.whitelist()
    def analyse_data(self, dont_save=0):
        self.check_permission("write")
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
                if 0.98 <= (flt(d.linked_doc_taxable_value) / (flt(d.taxable_value) + 1)) <= 1.02 and \
                        0.98 <= (flt(d.linked_doc_grand_total) / (flt(d.grand_total) + 1)) <= 1.02:
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
        """
        Sets the party of every row from its GSTIN, links Purchase Invoices by supplier invoice number, and
        copies the values of the linked documents. Constant number of queries for any number of rows.
        """
        parties = get_parties_from_gstins("Supplier", [d.party_gstin for d in self.invoices])
        for d in self.invoices:
            d.party_type, d.party, d.party_name = parties.get(d.party_gstin, ("", "", ""))

        to_link = [d for d in self.invoices
                   if d.party and d.party_type == "Supplier" and not d.linked_document_type]
        pi_map = get_pi_map_from_supplier_inv_nos([(d.party, d.supplier_invoice_no) for d in to_link])
        for d in to_link:
            pi_name = pi_map.get((d.party, d.supplier_invoice_no))
            d.linked_document_type, d.linked_document_name = ("Purchase Invoice", pi_name) if pi_name else ("", "")

        linked = [d for d in self.invoices if d.party and d.party_type == "Supplier"
                  and d.linked_document_type and d.linked_document_name]
        linked_values = get_linked_doc_values(linked)
        for d in linked:
            ldt = linked_values.get((d.linked_document_type, d.linked_document_name))
            if not ldt:
                frappe.throw(f"{d.linked_document_type} {d.linked_document_name} linked in Row# {d.idx} does not exist")
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
                             f"{frappe.get_desk_link(d.linked_document_type, d.linked_document_name)}")

    def create_new_table(self, resp):
        for d in resp:
            row = frappe._dict({})
            row_list = update_gstin_data(row, d)
            self.update_invoice_table(row_list)

    def update_invoice_table(self, row_list):
        for data in row_list:
            data = frappe._dict(data)
            self.append("invoices", data.copy())


def fetch_gstr2a_job(docname):
    """Background job: replaces the invoices table with GSTR2A from the GST Network and saves once."""
    doc = frappe.get_doc("GSTR2A RIGPL", docname)
    sections = {path: key for path, (key, _) in GSTR2A_SECTIONS.items()}
    try:
        gst_data = get_gstr2a(gstin=doc.gstin, ret_period=doc.return_period, sections=sections)
        doc.update_from_gst_network(gst_data)
        doc.save()
        counts = ", ".join(f"{name}: {len(gst_data.get(path) or [])}" for path, (_, name) in GSTR2A_SECTIONS.items())
        _notify(f"GSTR2A {doc.name} for {doc.return_period} is updated from the GST Network ({counts})",
                title="GSTR2A Updated", indicator="green")
    except Exception:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), f"GSTR2A Update Failed for {docname}")
        _notify(f"GSTR2A update for {docname} failed: {frappe.get_traceback().splitlines()[-1]}. "
                "Nothing was changed. See Error Log for details.", title="GSTR2A Update Failed", indicator="red")


def _notify(message, title, indicator):
    frappe.publish_realtime("msgprint", {"message": message, "title": title, "indicator": indicator},
                            user=frappe.session.user)


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
        for inv in gstin_resp.get("inv") or gstin_resp.get("nt") or []:
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


def get_parties_from_gstins(ptype, gstins):
    """{GSTIN: (party_type, party, party_name)} from the Addresses with that GSTIN, in one query."""
    gstins = list({g for g in gstins if g})
    if not gstins:
        return {}
    ad = frappe.qb.DocType("Address")
    dl = frappe.qb.DocType("Dynamic Link")
    rows = (
        frappe.qb.from_(ad).join(dl).on(dl.parent == ad.name)
        .select(ad.name, ad.address_title, ad.gstin, dl.link_doctype.as_("party_type"), dl.link_name.as_("party"))
        .where((dl.parenttype == "Address") & (dl.parentfield == "links") & ad.gstin.isin(gstins))
        # Dynamic Link name order: matches the row order the old unordered query returned
        .orderby(ad.name).orderby(dl.name)
        .run(as_dict=True)
    )
    add_lists = {}
    for row in rows:
        add_lists.setdefault(row.gstin, []).append(row)
    return {gstin: pick_party(add_list, ptype) for gstin, add_list in add_lists.items()}


def pick_party(add_list, ptype):
    """With one linked party, that party. With more, the last one of type ptype, or none."""
    if len(add_list) == 1:
        return add_list[0].party_type, add_list[0].party, add_list[0].address_title
    party_type, party, party_name = "", "", ""
    for d in add_list:
        if d.party_type == ptype:
            party_type, party, party_name = d.party_type, d.party, d.address_title
    return party_type, party, party_name


def get_pi_map_from_supplier_inv_nos(pairs):
    """{(supplier, supplier invoice no): Purchase Invoice} for non-cancelled invoices, in one query."""
    pairs = {p for p in pairs if p[0] and p[1]}
    if not pairs:
        return {}
    invoices = frappe.get_all("Purchase Invoice",
                              filters={"docstatus": ["!=", 2], "supplier": ["in", list({p[0] for p in pairs})],
                                       "bill_no": ["in", list({p[1] for p in pairs})]},
                              fields=["name", "supplier", "bill_no"], order_by="creation")
    pi_map = {}
    for pi in invoices:
        if (pi.supplier, pi.bill_no) in pairs:
            pi_map.setdefault((pi.supplier, pi.bill_no), pi.name)
    return pi_map


def get_linked_doc_values(rows):
    """{(doctype, name): values} for the Purchase Invoices and Journal Entries linked in rows. One query each."""
    fields_by_doctype = {
        "Purchase Invoice": ["name", "docstatus", "base_total", "base_grand_total"],
        "Journal Entry": ["name", "docstatus", "total_debit"],
    }
    names_by_doctype = {}
    for d in rows:
        if d.linked_document_type not in fields_by_doctype:
            frappe.throw(f"Linked Document Type {d.linked_document_type} in Row# {d.idx} is Not Supported. "
                         "Use Purchase Invoice or Journal Entry.")
        names_by_doctype.setdefault(d.linked_document_type, set()).add(d.linked_document_name)
    values = {}
    for doctype, names in names_by_doctype.items():
        for doc in frappe.get_all(doctype, filters={"name": ["in", list(names)]}, fields=fields_by_doctype[doctype]):
            values[(doctype, doc.name)] = doc
    return values

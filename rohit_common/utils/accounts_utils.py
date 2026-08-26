#  Copyright (c) 2021. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
import frappe
from frappe.utils import flt


def get_inv_status(inv_status):
    if inv_status == "A":
        return "A-Accepted"
    elif inv_status == "R":
        return "R-Rejected"
    elif inv_status == "N":
        return "N-No Action"
    elif inv_status == "U":
        return "U-Uploaded"
    elif inv_status == "P":
        return "P-Pending"
    else:
        frappe.throw(f"{inv_status} is Not Yet Supported")


def get_invoice_uploader(upload_short):
    if upload_short == "R":
        return "R-Receiver"
    elif upload_short == "S":
        return "S-Supplier"
    else:
        frappe.throw(f"{upload_short} is Not Valid Type of Invoice Uploader Type")


def get_hsn_sum_frm_si(si_name):
    sid = frappe.get_doc("Sales Invoice", si_name)
    hsn_sum = []
    for row in sid.items:
        if not hsn_sum:
            hsn_dict = make_hsn_sum_dict(sid, row)
            hsn_sum.append(hsn_dict.copy())
        else:
            found = 0
            for hsn in hsn_sum:
                if hsn.hsn == row.gst_hsn_code:
                    if hsn.uom == row.stock_uom:
                        found = 1
                        tax_rate, sgst_amt, cgst_amt, igst_amt, cess_amt = get_taxes_from_sid(sid)
                        if sid.base_net_total > 0:
                            row_igst = round((igst_amt * row.base_net_amount / sid.base_net_total), 2)
                            row_sgst = round((sgst_amt * row.base_net_amount / sid.base_net_total), 2)
                            row_cgst = round((cgst_amt * row.base_net_amount / sid.base_net_total), 2)
                            row_cess = round((cess_amt * row.base_net_amount / sid.base_net_total), 2)
                        else:
                            row_igst, row_sgst, row_cgst, row_cess = 0, 0, 0, 0
                        row_tot_val = row.base_net_amount + row_igst + row_cgst + row_sgst + row_cess
                        hsn.total_quantity += row.qty
                        hsn.total_taxable_value += row.base_net_amount
                        hsn.igst += row_igst
                        hsn.cgst += row_cgst
                        hsn.sgst += row_sgst
                        hsn.cess += row_cess
                        hsn.total_value += row_tot_val
            if found != 1:
                hsn_dict = make_hsn_sum_dict(sid, row)
                hsn_sum.append(hsn_dict.copy())
    return hsn_sum


def make_hsn_sum_dict(sid, row):
    tax_rate, sgst_amt, cgst_amt, igst_amt, cess_amt = get_taxes_from_sid(sid)
    if sid.base_net_total > 0:
        row_igst = round((igst_amt * row.base_net_amount / sid.base_net_total), 2)
        row_sgst = round((sgst_amt * row.base_net_amount / sid.base_net_total), 2)
        row_cgst = round((cgst_amt * row.base_net_amount / sid.base_net_total), 2)
        row_cess = round((cess_amt * row.base_net_amount / sid.base_net_total), 2)
    else:
        row_igst, row_sgst, row_cgst, row_cess = 0, 0, 0, 0
    row_tot_val = row.base_net_amount + row_igst + row_cgst + row_sgst + row_cess
    hsn_dict = frappe._dict({})
    hsn_dict["hsn"] = row.gst_hsn_code
    hsn_dict["total_quantity"] = row.qty
    hsn_dict["uom"] = row.stock_uom
    hsn_dict["total_taxable_value"] = row.base_net_amount
    hsn_dict["igst"] = row_igst
    hsn_dict["sgst"] = row_sgst
    hsn_dict["cgst"] = row_cgst
    hsn_dict["cess"] = row_cess
    hsn_dict["total_value"] = row_tot_val
    return hsn_dict


def get_linked_type_from_jv(jv_name):
    linked_dt, linked_dn = "", ""
    jvd = frappe.get_doc("Journal Entry", jv_name)
    for row in jvd.accounts:
        if row.party_type:
            linked_dt = row.party_type
            linked_dn = row.party
            break
    return linked_dt, linked_dn


def guess_correct_address(linked_dt, linked_dn):
    all_addresses = frappe.db.sql("""SELECT a1.name, a1.gstin, a1.validated_gstin
        FROM `tabAddress` a1, `tabDynamic Link` dl
        WHERE dl.parent= a1.name AND dl.parenttype = 'Address' AND dl.link_doctype = '%s'
        AND dl.link_name = '%s' GROUP BY a1.gstin ORDER BY a1.gstin""" % (linked_dt, linked_dn), as_dict=1)
    if len(all_addresses) == 1:
        return all_addresses[0].name
    elif len(all_addresses) == 0:
        frappe.throw(f"No Address in System for {linked_dt}: {linked_dn}")
    else:
        # Now we would need to guess if gstin is same on all address then use any
        # If GSTIN is different and Valid then its a problem
        # If only 1 GSTIN is valid then use valid GSTIN address
        for a in all_addresses:
            if a.validated_gstin == a.gstin:
                return a.name
        frappe.msgprint(f"There are {len(all_addresses)} Address for {linked_dt}: {linked_dn}")
        return all_addresses[0].name


def get_gst_export_fields(si_doc, tax_template=None):
    shb, shd_date, tax_payment, port_code = "", "", "", ""
    if tax_template is None:
        tax_template = frappe.get_doc("Sales Taxes and Charges Template", si_doc.taxes_and_charges)
    if tax_template.is_export == 1:
        shb = si_doc.shipping_bill_number
        shb_date = si_doc.shipping_bill_date
        tax_payment = tax_template.export_type
        port_code = si_doc.port_code
    return shb, shb_date, tax_payment, port_code


def get_gst_jv_type(jv_doc):
    jv_type = ""
    for acc in jv_doc.accounts:
        if acc.party_type:
            if acc.credit_in_account_currency > 0:
                return "credit"
            elif acc.debit_in_account_currency > 0:
                return "debit"


def get_gst_si_type(si_doc, tax_template=None):
    if tax_template is None:
        tax_template = frappe.get_doc("Sales Taxes and Charges Template", si_doc.taxes_and_charges)
    if si_doc.is_return != 1:
        if tax_template.is_export == 1:
            return "export"
        elif si_doc.billing_address_gstin == "NA":
            if si_doc.base_grand_total >= 250000:
                return "b2cl"
            else:
                return "b2c"
        else:
            return "b2b"
    else:
        if si_doc.billing_address_gstin == "NA":
            return "cdn_b2c"
        else:
            return "cdn_b2b"


def get_gst_accounts_list(gst_set=None):
    """Build the cgst/sgst/igst/cess account list from GST Settings.

    Pass a pre-fetched `gst_set` (or the return value of this function,
    via `get_taxes_from_jvd`/`get_taxes_from_sid`'s `gst_accounts` param)
    when processing many rows in a loop, instead of re-fetching GST
    Settings once per row.
    """
    if gst_set is None:
        gst_set = frappe.get_doc("GST Settings", "GST Setting")
    gst_taxes = []
    for d in gst_set.gst_accounts:
        gst_dict = frappe._dict({})
        gst_dict["cgst"] = d.cgst_account
        gst_dict["sgst"] = d.sgst_account
        gst_dict["igst"] = d.igst_account
        gst_dict["cess"] = d.cess_account
        gst_taxes.append(gst_dict.copy())
    return gst_taxes


def get_taxes_from_jvd(jvd, jv_type, gst_accounts=None):
    tax_rate, sgst_amt, cgst_amt, igst_amt, cess_amt, net_amt = 0, 0, 0, 0, 0, 0
    if jv_type == "credit":
        acc_type = "debit"
    elif jv_type == "debit":
        acc_type = "credit"
    else:
        acc_type = ""
    if gst_accounts is None:
        gst_accounts = get_gst_accounts_list()
    if not gst_accounts:
        frappe.throw("No GST Accounts Setup in GST Settings")
    gst_taxes = gst_accounts
    for acc in jvd.accounts:
        if acc.account not in gst_taxes[0].values():
            net_amt += acc.get(acc_type + "_in_account_currency", 0)
        for gst in gst_taxes:
            found = 0
            row_amt = acc.get(acc_type + "_in_account_currency", 0)
            if acc.account == gst.cgst:
                cgst_amt += row_amt
                found = 1
            elif acc.account == gst.sgst:
                sgst_amt += row_amt
                found = 1
            elif acc.account == gst.igst:
                igst_amt += row_amt
                found = 1
            elif acc.account == gst.cess:
                cess_amt += row_amt
    tax_rate = round((((sgst_amt + cgst_amt + igst_amt) / net_amt) * 100), 0)

    return tax_rate, sgst_amt, cgst_amt, igst_amt, cess_amt, net_amt


def get_taxes_from_sid(sid, gst_accounts=None):
    tax_rate, sgst_amt, cgst_amt, igst_amt, cess_amt = 0, 0 ,0 ,0, 0
    if gst_accounts is None:
        gst_accounts = get_gst_accounts_list()
    for acc in sid.taxes:
        for gst in gst_accounts:
            found = 0
            if acc.account_head == gst.cgst:
                cgst_amt += acc.base_tax_amount
                found = 1
            elif acc.account_head == gst.sgst:
                sgst_amt += acc.base_tax_amount
                found = 1
            elif acc.account_head == gst.igst:
                igst_amt += acc.base_tax_amount
                found = 1
            elif acc.account_head == gst.cess:
                cess_amt += acc.base_tax_amount
            if found == 1:
                tax_rate += acc.rate
    return tax_rate, sgst_amt, cgst_amt, igst_amt, cess_amt


def get_base_doc_frm_docname(dt, dn):
    try:
        doc = frappe.get_doc(dt, dn)
    except:
        return ""
    base_doc_no = get_base_doc_no(doc)
    return base_doc_no


def get_base_doc_no(sid):
    if sid.amended_from:
        si_base_doc = frappe.get_doc(sid.doctype, sid.amended_from)
        return get_base_doc_no(si_base_doc)
    else:
        return sid.name


def set_advances(self):
    """
    Returns list of advances against Account, Party, Reference.
    Also advances should have clearance date if received in Bank and not in Cash
    """

    res = self.get_advance_entries()
    self.set("advances", [])
    advance_allocated = 0
    for d in res:
        if d.against_order:
            allocated_amount = flt(d.amount)
        else:
            amount = self.rounded_total or self.base_grand_total
            allocated_amount = min(amount - advance_allocated, d.amount)
        advance_allocated += flt(allocated_amount)

        self.append("advances", {
            "doctype": self.doctype + " Advance",
            "reference_type": d.reference_type,
            "reference_name": d.reference_name,
            "reference_row": d.reference_row,
            "remarks": d.remarks,
            "advance_amount": flt(d.amount),
            "allocated_amount": allocated_amount
        })


def get_advance_entries(self, include_unallocated=True):
    if self.doctype == "Sales Invoice":
        party_account = self.debit_to
        party_type = "Customer"
        party = self.customer
        amount_field = "credit_in_account_currency"
        order_field = "sales_order"
        order_doctype = "Sales Order"
    else:
        party_account = self.credit_to
        party_type = "Supplier"
        party = self.supplier
        amount_field = "debit_in_account_currency"
        order_field = "purchase_order"
        order_doctype = "Purchase Order"

    order_list = list(set([d.get(order_field)
                           for d in self.get("items") if d.get(order_field)]))

    journal_entries = get_advance_journal_entries(party_type, party, party_account,
                                                  amount_field, order_doctype, order_list, include_unallocated)

    payment_entries = get_advance_payment_entries(party_type, party, party_account,
                                                  order_doctype, order_list, include_unallocated)

    res = journal_entries + payment_entries

    return res


def get_advance_journal_entries(party_type, party, party_account, amount_field, order_doctype, order_list,
                                include_unallocated=True):
    dr_or_cr = "credit_in_account_currency" if party_type == "Customer" else "debit_in_account_currency"
    conditions = []
    if include_unallocated:
        conditions.append("IFNULL(t2.reference_name, '')=''")
    if order_list:
        order_condition = ', '.join(['%s'] * len(order_list))
        conditions.append(f" (t2.reference_type = '{order_doctype}' and IFNULL(t2.reference_name, '') IN "
                          f"({order_condition}))")
    reference_condition = " AND (" + " OR ".join(conditions) + ")" if conditions else ""

    journal_entries = frappe.db.sql(f"""SELECT "Journal Entry" as reference_type, t1.name as reference_name,
            t1.remark as remarks, t2.{0} as amount, t2.name as reference_row, t2.reference_name as against_order
            FROM `tabJournal Entry` t1, `tabJournal Entry Account` t2 WHERE t1.name = t2.parent and t2.account = %s
            AND t2.party_type = %s and t2.party = %s AND t2.is_advance = 'Yes' and t1.docstatus = 1 AND {1} > 0 {2}
            ORDER BY t1.posting_date""".format(amount_field, dr_or_cr, reference_condition),
                                    [party_account, party_type, party] + order_list, as_dict=1)
    return list(journal_entries)


def get_advance_payment_entries(party_type, party, party_account, order_doctype, order_list=None,
                                include_unallocated=True, against_all_orders=False, limit=None):
    party_account_field = "paid_from" if party_type == "Customer" else "paid_to"
    currency_field = "paid_from_account_currency" if party_type == "Customer" else "paid_to_account_currency"
    payment_type = "Receive" if party_type == "Customer" else "Pay"
    payment_entries_against_order, unallocated_payment_entries = [], []
    limit_cond = "LIMIT %s" % limit if limit else ""

    if order_list or against_all_orders:
        if order_list:
            reference_condition = f" AND t2.reference_name IN ({', '.join(['%s'] * len(order_list))})"
        else:
            reference_condition = ""
            order_list = []

        payment_entries_against_order = frappe.db.sql("""SELECT "Payment Entry" as reference_type,
        t1.name as reference_name, t1.remarks, t2.allocated_amount as amount, t2.name as reference_row,
        t2.reference_name as against_order, t1.posting_date, t1.{0} as currency
        FROM `tabPayment Entry` t1, `tabPayment Entry Reference` t2 WHERE t1.name = t2.parent
        AND t1.{1} = %s AND t1.payment_type = %s AND t1.party_type = %s AND t1.party = %s AND t1.docstatus = 1
        AND t2.reference_doctype = %s {2}
        ORDER BY t1.posting_date {3}""".format(currency_field, party_account_field, reference_condition, limit_cond),
                                                      [party_account, payment_type, party_type, party,
                                                       order_doctype] + order_list, as_dict=1)

    if include_unallocated:
        unallocated_payment_entries = frappe.db.sql("""SELECT "Payment Entry" as reference_type, name as reference_name,
        remarks, unallocated_amount as amount FROM `tabPayment Entry` WHERE {0} = %s AND party_type = %s AND party = %s
        AND payment_type = %s AND docstatus = 1 AND unallocated_amount > 0
        ORDER BY posting_date {1}""".format(party_account_field, limit_cond), (party_account, party_type, party,
                                                                               payment_type), as_dict=1)

    return list(payment_entries_against_order) + list(unallocated_payment_entries)

#  Copyright (c) 2021. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
import frappe
from frappe.utils import flt

GST_TAX_TYPES = ("cgst", "sgst", "igst", "cess")


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


def get_gst_accounts():
    """
    GST account heads from GST Settings, one dict per GST Settings row with keys cgst/sgst/igst/cess.
    One query. Callers that process many documents should call it once and pass the result on.
    """
    rows = frappe.get_all("GST Account", filters={"parenttype": "GST Settings", "parentfield": "gst_accounts"},
                          fields=["cgst_account", "sgst_account", "igst_account", "cess_account"], order_by="idx")
    return [frappe._dict({tax: row.get(f"{tax}_account") for tax in GST_TAX_TYPES}) for row in rows]


def get_hsn_sum_frm_si(si_name):
    return get_hsn_summary_for_invoices([si_name])


def get_hsn_summary_for_invoices(si_names):
    """
    HSN-wise summary (grouped by HSN and UOM) of the given Sales Invoices, in a constant number of queries.
    """
    if not si_names:
        return []
    items = frappe.get_all("Sales Invoice Item", filters={"parenttype": "Sales Invoice", "parentfield": "items", "parent": ["in", si_names]},
                           fields=["parent", "gst_hsn_code", "stock_uom", "qty", "base_net_amount"],
                           order_by="idx")
    net_total_by_si = {si.name: si.base_net_total for si in frappe.get_all(
        "Sales Invoice", filters={"name": ["in", si_names]}, fields=["name", "base_net_total"])}
    taxes_by_si = get_si_taxes_map(si_names, get_gst_accounts())
    items_by_si = {}
    for row in items:
        items_by_si.setdefault(row.parent, []).append(row)
    ordered_items = [row for si in si_names for row in items_by_si.get(si, [])]
    return build_hsn_summary(ordered_items, net_total_by_si, taxes_by_si)


def build_hsn_summary(items, net_total_by_si, taxes_by_si):
    """
    Groups Sales Invoice Item rows by (HSN, UOM). The invoice tax is allocated to each item row in proportion
    to its net amount and rounded to 2 decimals per row. Sorted by HSN; rows with the same HSN keep their
    first-seen order.
    taxes_by_si: {invoice: (tax_rate, sgst, cgst, igst, cess)} as returned by get_si_taxes_map().
    """
    summary = {}
    for row in items:
        tax_rate, sgst_amt, cgst_amt, igst_amt, cess_amt = taxes_by_si[row.parent]
        net_total = net_total_by_si[row.parent]
        if net_total > 0:
            row_igst = round((igst_amt * row.base_net_amount / net_total), 2)
            row_sgst = round((sgst_amt * row.base_net_amount / net_total), 2)
            row_cgst = round((cgst_amt * row.base_net_amount / net_total), 2)
            row_cess = round((cess_amt * row.base_net_amount / net_total), 2)
        else:
            row_igst, row_sgst, row_cgst, row_cess = 0, 0, 0, 0
        row_tot_val = row.base_net_amount + row_igst + row_cgst + row_sgst + row_cess
        key = (row.gst_hsn_code, row.stock_uom)
        hsn = summary.get(key)
        if not hsn:
            summary[key] = frappe._dict({
                "hsn": row.gst_hsn_code, "total_quantity": row.qty, "uom": row.stock_uom,
                "total_taxable_value": row.base_net_amount, "igst": row_igst, "sgst": row_sgst,
                "cgst": row_cgst, "cess": row_cess, "total_value": row_tot_val})
        else:
            hsn.total_quantity += row.qty
            hsn.total_taxable_value += row.base_net_amount
            hsn.igst += row_igst
            hsn.cgst += row_cgst
            hsn.sgst += row_sgst
            hsn.cess += row_cess
            hsn.total_value += row_tot_val
    return sorted(summary.values(), key=lambda i: i["hsn"])


def get_linked_type_from_jv(jv_name):
    party = get_jv_party_map([jv_name]).get(jv_name)
    return party or ("", "")


def get_jv_party_map(jv_names):
    """{Journal Entry: (party_type, party)} from the first account row with a party. One query."""
    if not jv_names:
        return {}
    rows = frappe.get_all("Journal Entry Account",
                          filters={"parenttype": "Journal Entry", "parentfield": "accounts", "parent": ["in", list(jv_names)],
                                   "party_type": ["is", "set"]},
                          fields=["parent", "party_type", "party"], order_by="idx")
    party_map = {}
    for row in rows:
        party_map.setdefault(row.parent, (row.party_type, row.party))
    return party_map


def guess_correct_address(linked_dt, linked_dn):
    addresses = get_party_addresses([(linked_dt, linked_dn)]).get((linked_dt, linked_dn), [])
    return pick_address(addresses, linked_dt, linked_dn)


def get_party_addresses(parties):
    """{(link_doctype, link_name): [Address rows]} for all given parties, in one query."""
    parties = {p for p in parties if p[0] and p[1]}
    if not parties:
        return {}
    ad = frappe.qb.DocType("Address")
    dl = frappe.qb.DocType("Dynamic Link")
    rows = (
        frappe.qb.from_(ad).join(dl).on(dl.parent == ad.name)
        .select(ad.name, ad.gstin, ad.validated_gstin, ad.address_title, dl.link_doctype, dl.link_name)
        .where((dl.parenttype == "Address") & (dl.parentfield == "links") & dl.link_name.isin([p[1] for p in parties]))
        # Dynamic Link name order: matches the row order the old GROUP BY query picked from
        .orderby(ad.gstin).orderby(dl.name)
        .run(as_dict=True)
    )
    by_party = {}
    for row in rows:
        key = (row.link_doctype, row.link_name)
        if key in parties:
            by_party.setdefault(key, []).append(row)
    return by_party


def pick_address(addresses, linked_dt, linked_dn):
    """
    Picks the billing address of a party: the only address, or else the first with a validated GSTIN, or else
    the first. Addresses with the same GSTIN count once.
    """
    unique_by_gstin = {}
    for add in addresses:
        unique_by_gstin.setdefault(add.gstin, add)
    all_addresses = list(unique_by_gstin.values())
    if len(all_addresses) == 1:
        return all_addresses[0].name
    elif len(all_addresses) == 0:
        frappe.throw(f"No Address in System for {linked_dt}: {linked_dn}")
    else:
        # If GSTIN is different and Valid then its a problem
        # If only 1 GSTIN is valid then use valid GSTIN address
        for a in all_addresses:
            if a.validated_gstin == a.gstin:
                return a.name
        frappe.msgprint(f"There are {len(all_addresses)} Address for {linked_dt}: {linked_dn}")
        return all_addresses[0].name


def get_gst_export_fields(si_doc):
    if not si_doc.taxes_and_charges:
        frappe.throw(f"Sales Taxes and Charges Template is not set in {si_doc.doctype} {si_doc.name}")
    template = frappe.db.get_value("Sales Taxes and Charges Template", si_doc.taxes_and_charges,
                                   ["is_export", "export_type"], as_dict=True)
    return export_fields(si_doc, template)


def export_fields(si, template):
    shb, shb_date, tax_payment, port_code = "", "", "", ""
    if template and template.is_export == 1:
        shb = si.shipping_bill_number
        shb_date = si.shipping_bill_date
        tax_payment = template.export_type
        port_code = si.port_code
    return shb, shb_date, tax_payment, port_code


def get_gst_jv_type(jv_doc):
    return gst_jv_type(jv_doc.accounts)


def gst_jv_type(jv_accounts):
    for acc in jv_accounts:
        if acc.party_type:
            if acc.credit_in_account_currency > 0:
                return "credit"
            elif acc.debit_in_account_currency > 0:
                return "debit"


def get_gst_si_type(si_doc):
    if not si_doc.taxes_and_charges:
        frappe.throw(f"Sales Taxes and Charges Template is not set in {si_doc.doctype} {si_doc.name}")
    is_export = frappe.db.get_value("Sales Taxes and Charges Template", si_doc.taxes_and_charges, "is_export")
    return gst_si_type(si_doc, is_export)


def gst_si_type(si, is_export):
    if si.is_return != 1:
        if is_export == 1:
            return "export"
        elif si.billing_address_gstin == "NA":
            if si.base_grand_total >= 250000:
                return "b2cl"
            else:
                return "b2c"
        else:
            return "b2b"
    else:
        if si.billing_address_gstin == "NA":
            return "cdn_b2c"
        else:
            return "cdn_b2b"


def get_taxes_from_jvd(jvd, jv_type):
    return taxes_from_jv_accounts(jvd.accounts, jv_type, get_gst_accounts())


def taxes_from_jv_accounts(jv_accounts, jv_type, gst_taxes):
    tax_rate, sgst_amt, cgst_amt, igst_amt, cess_amt, net_amt = 0, 0, 0, 0, 0, 0
    if jv_type == "credit":
        acc_type = "debit"
    elif jv_type == "debit":
        acc_type = "credit"
    else:
        acc_type = ""
    if not gst_taxes:
        frappe.throw("No GST Accounts Setup in GST Settings")
    for acc in jv_accounts:
        row_amt = acc.get(acc_type + "_in_account_currency", 0)
        if acc.account not in gst_taxes[0].values():
            net_amt += row_amt
        for gst in gst_taxes:
            if acc.account == gst.cgst:
                cgst_amt += row_amt
            elif acc.account == gst.sgst:
                sgst_amt += row_amt
            elif acc.account == gst.igst:
                igst_amt += row_amt
            elif acc.account == gst.cess:
                cess_amt += row_amt
    tax_rate = round((((sgst_amt + cgst_amt + igst_amt) / net_amt) * 100), 0)

    return tax_rate, sgst_amt, cgst_amt, igst_amt, cess_amt, net_amt


def get_taxes_from_sid(sid):
    return taxes_from_si_rows(sid.taxes, get_gst_accounts())


def get_si_taxes_map(si_names, gst_taxes):
    """{Sales Invoice: (tax_rate, sgst, cgst, igst, cess)} for all given invoices, in one query."""
    rows = frappe.get_all("Sales Taxes and Charges",
                          filters={"parenttype": "Sales Invoice", "parentfield": "taxes", "parent": ["in", list(si_names)]},
                          fields=["parent", "account_head", "base_tax_amount", "rate"], order_by="idx")
    rows_by_si = {si: [] for si in si_names}
    for row in rows:
        rows_by_si[row.parent].append(row)
    return {si: taxes_from_si_rows(tax_rows, gst_taxes) for si, tax_rows in rows_by_si.items()}


def taxes_from_si_rows(tax_rows, gst_taxes):
    tax_rate, sgst_amt, cgst_amt, igst_amt, cess_amt = 0, 0, 0, 0, 0
    for acc in tax_rows:
        for gst in gst_taxes:
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
    return get_base_doc_map(dt, [dn]).get(dn, "")


def get_base_doc_no(sid):
    if sid.amended_from:
        base_doc_no = get_base_doc_map(sid.doctype, [sid.amended_from]).get(sid.amended_from)
        if not base_doc_no:
            frappe.throw(f"Amendment chain of {sid.doctype} {sid.name} is broken: {sid.amended_from} or one of "
                         f"its earlier versions does not exist")
        return base_doc_no
    else:
        return sid.name


def get_base_doc_map(doctype, names):
    """
    {name: first document of its amended_from chain} for the given names. One query per amendment depth,
    not one per document. A name that does not exist, or whose chain points to a missing document, is not
    in the result.
    """
    parent_of = {}
    pending = {n for n in names if n}
    while pending:
        rows = frappe.get_all(doctype, filters={"name": ["in", list(pending)]}, fields=["name", "amended_from"])
        pending = set()
        for row in rows:
            parent_of[row.name] = row.amended_from
        for row in rows:
            if row.amended_from and row.amended_from not in parent_of:
                pending.add(row.amended_from)
    base_map = {}
    for name in names:
        if name not in parent_of:
            continue
        current = name
        seen = {current}
        while parent_of.get(current):
            current = parent_of[current]
            if current in seen:
                frappe.throw(f"{doctype} {name} has a circular amended_from chain")
            seen.add(current)
        if current in parent_of:
            base_map[name] = current
    return base_map


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

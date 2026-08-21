#  Copyright (c) 2021. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt

from __future__ import unicode_literals
import frappe
import datetime


def execute(filters=None):
    if not filters: filters = {}

    columns = get_columns()
    data = get_sl_entries(filters)

    return columns, data


def get_columns():
    return [ "Date:Date:80", "Time:Time:80", "Item:Link/Item:130", "Description::350", "Qty:Float:60",
             "Balance:Float:90", "Warehouse:Link/Warehouse:120",
            {
                "label": "Voucher No",
                "fieldname": "voucher_no",
                "fieldtype": "Dynamic Link",
                "options": "voucher_type",
                "width": 130
            },
            {
                "label": "Voucher Type",
                "fieldname": "voucher_type",
                "width": 140
            },
            {
                "label": "Linked Name",
                "fieldname": "linked_name",
                "fieldtype": "Dynamic Link",
                "options": "link_type",
                "width": 150
            }, "Name::100",
            {
                "label": "Link Type",
                "fieldname": "link_type",
                "width": 50
            },
    ]


# voucher_type -> field on that doctype holding the party to show as "Linked Name"
PARTY_FIELD_BY_VOUCHER_TYPE = {
    "Delivery Note": ("customer", "Customer"),
    "Sales Invoice": ("customer", "Customer"),
    "Purchase Receipt": ("supplier", "Supplier"),
    "Purchase Invoice": ("supplier", "Supplier"),
}

# Stock Entry has no single party field - it links back to whichever document
# triggered it. Same priority order as the original per-row frappe.get_doc()
# implementation.
STOCK_ENTRY_LINK_PRIORITY = [
    ("process_job_card", "Process Job Card RIGPL"),
    ("sales_order", "Sales Order"),
    ("delivery_note_no", "Delivery Note"),
    ("sales_invoice_no", "Sales Invoice"),
    ("purchase_order", "Purchase Order"),
    ("purchase_receipt_no", "Purchase Receipt"),
]


def get_sl_entries(filters):
    conditions, conditions_item, values = get_conditions(filters)

    temp_data = frappe.db.sql("""SELECT sle.posting_date, sle.posting_time, sle.item_code, it.description,
        sle.actual_qty, sle.qty_after_transaction, sle.warehouse, sle.voucher_no, sle.voucher_type,
        sle.name FROM `tabStock Ledger Entry` sle, `tabItem` it WHERE sle.is_cancelled = 'No'
        AND sle.item_code = it.name {0} {1} ORDER BY sle.posting_date DESC, sle.posting_time DESC,
        sle.name DESC""".format(conditions, conditions_item), values, as_dict=1)

    voucher_names_by_type = {}
    for d in temp_data:
        voucher_names_by_type.setdefault(d.voucher_type, set()).add(d.voucher_no)

    party_by_voucher = get_party_by_voucher(voucher_names_by_type)
    stock_entry_by_name = get_stock_entries(voucher_names_by_type.get("Stock Entry"))

    for d in temp_data:
        d["posting_time"] = d["posting_time"] - datetime.timedelta(microseconds=d["posting_time"].microseconds)

        if d.voucher_type in PARTY_FIELD_BY_VOUCHER_TYPE:
            _, link_type = PARTY_FIELD_BY_VOUCHER_TYPE[d.voucher_type]
            if (d.voucher_type, d.voucher_no) not in party_by_voucher:
                frappe.throw(
                    "{0} {1} referenced by Stock Ledger Entry {2} was not found"
                    .format(d.voucher_type, d.voucher_no, d.name)
                )
            d["link_type"] = link_type
            d["linked_name"] = party_by_voucher[(d.voucher_type, d.voucher_no)]
        elif d.voucher_type == "Stock Entry":
            if d.voucher_no not in stock_entry_by_name:
                frappe.throw(
                    "Stock Entry {0} referenced by Stock Ledger Entry {1} was not found"
                    .format(d.voucher_no, d.name)
                )
            d["link_type"], d["linked_name"] = get_stock_entry_link(stock_entry_by_name[d.voucher_no])
        else:
            d["link_type"] = None
            d["linked_name"] = None

    data = []
    for d in temp_data:
        row = [d.posting_date, d.posting_time, d.item_code, d.description, d.actual_qty, d.qty_after_transaction,
               d.warehouse, d.voucher_no, d.voucher_type, d.linked_name, d.name, d.link_type]
        data.append(row)

    return data


def get_party_by_voucher(voucher_names_by_type):
    """Batch fetch the customer/supplier for every DN/SI/PR/PI voucher in the
    result set - one frappe.get_all() per doctype instead of one frappe.get_doc()
    per row."""
    party_by_voucher = {}
    for voucher_type, (fieldname, _link_type) in PARTY_FIELD_BY_VOUCHER_TYPE.items():
        names = voucher_names_by_type.get(voucher_type)
        if not names:
            continue
        rows = frappe.get_all(
            voucher_type,
            filters=[["name", "in", list(names)]],
            fields=["name", fieldname],
        )
        for row in rows:
            party_by_voucher[(voucher_type, row.name)] = row.get(fieldname)

    return party_by_voucher


def get_stock_entries(names):
    """Batch fetch the link fields needed to resolve a Stock Entry's origin
    document - one frappe.get_all() instead of one frappe.get_doc() per row."""
    if not names:
        return {}

    fields = ["name"] + [fieldname for fieldname, _link_type in STOCK_ENTRY_LINK_PRIORITY]
    rows = frappe.get_all("Stock Entry", filters=[["name", "in", list(names)]], fields=fields)
    return {row.name: row for row in rows}


def get_stock_entry_link(stock_entry):
    for fieldname, link_type in STOCK_ENTRY_LINK_PRIORITY:
        if stock_entry.get(fieldname) is not None:
            return link_type, stock_entry.get(fieldname)

    return None, None


def get_conditions(filters):
    conditions = ""
    conditions_item = ""
    values = {}

    if filters.get("item"):
        conditions += " AND sle.item_code = %(item)s"
        conditions_item += " AND it.name = %(item)s"
        values["item"] = filters["item"]

    if filters.get("warehouse"):
        conditions += " AND sle.warehouse = %(warehouse)s"
        values["warehouse"] = filters["warehouse"]

    if filters.get("from_date"):
        conditions += " AND sle.posting_date >= %(from_date)s"
        values["from_date"] = filters["from_date"]

    if filters.get("to_date"):
        conditions += " AND sle.posting_date <= %(to_date)s"
        values["to_date"] = filters["to_date"]

    return conditions, conditions_item, values

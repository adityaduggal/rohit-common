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


def get_sl_entries(filters):
    conditions, params = get_conditions(filters)
    
    # Secure and efficient bulk query with explicit JOIN
    temp_data = frappe.db.sql(f"""
        SELECT 
            sle.posting_date, sle.posting_time, sle.item_code, it.description,
            sle.actual_qty, sle.qty_after_transaction, sle.warehouse, 
            sle.voucher_no, sle.voucher_type, sle.name
        FROM `tabStock Ledger Entry` sle
        INNER JOIN `tabItem` it ON sle.item_code = it.name
        WHERE sle.is_cancelled = 'No' 
        {conditions} 
        ORDER BY sle.posting_date DESC, sle.posting_time DESC, sle.name DESC
    """, params, as_dict=1)

    if not temp_data:
        return []

    # O(N) Batch Processing Strategy
    voucher_map = {}
    for d in temp_data:
        vt = d.voucher_type
        vn = d.voucher_no
        if vt not in voucher_map:
            voucher_map[vt] = set()
        voucher_map[vt].add(vn)

    # Bulk fetch linked names for each voucher type
    linked_data = {}
    for vt, vnos in voucher_map.items():
        vnos_list = list(vnos)
        if vt in ('Delivery Note', 'Sales Invoice'):
            field = "customer"
        elif vt in ('Purchase Receipt', 'Purchase Invoice'):
            field = "supplier"
        elif vt == "Stock Entry":
            # For Stock Entry we need more fields
            res = frappe.get_all(vt, 
                filters={"name": ["in", vnos_list]}, 
                fields=["name", "process_job_card", "sales_order", "delivery_note_no", 
                        "sales_invoice_no", "purchase_order", "purchase_receipt_no"])
            for r in res:
                lt, ln = None, None
                if r.process_job_card: lt, ln = "Process Job Card RIGPL", r.process_job_card
                elif r.sales_order: lt, ln = "Sales Order", r.sales_order
                elif r.delivery_note_no: lt, ln = "Delivery Note", r.delivery_note_no
                elif r.sales_invoice_no: lt, ln = "Sales Invoice", r.sales_invoice_no
                elif r.purchase_order: lt, ln = "Purchase Order", r.purchase_order
                elif r.purchase_receipt_no: lt, ln = "Purchase Receipt", r.purchase_receipt_no
                
                linked_data[(vt, r.name)] = {"link_type": lt, "linked_name": ln}
            continue
        else:
            continue

        res = frappe.get_all(vt, filters={"name": ["in", vnos_list]}, fields=["name", field])
        for r in res:
            linked_data[(vt, r.name)] = {
                "link_type": "Customer" if field == "customer" else "Supplier",
                "linked_name": r.get(field)
            }

    data = []
    for d in temp_data:
        # Posting time cleanup
        if d.posting_time:
            d["posting_time"] = d["posting_time"] - datetime.timedelta(microseconds=d["posting_time"].microseconds)
        
        info = linked_data.get((d.voucher_type, d.voucher_no), {"link_type": None, "linked_name": None})
        
        data.append([
            d.posting_date, d.posting_time, d.item_code, d.description, d.actual_qty, d.qty_after_transaction,
            d.warehouse, d.voucher_no, d.voucher_type, info["linked_name"], d.name, info["link_type"]
        ])

    return data

def get_conditions(filters):
    conditions = ""
    params = {}

    if filters.get("item"):
        conditions += " AND sle.item_code = %(item)s"
        params["item"] = filters["item"]

    if filters.get("warehouse"):
        conditions += " AND sle.warehouse = %(warehouse)s"
        params["warehouse"] = filters["warehouse"]

    if filters.get("from_date"):
        conditions += " AND sle.posting_date >= %(from_date)s"
        params["from_date"] = filters["from_date"]

    if filters.get("to_date"):
        conditions += " AND sle.posting_date <= %(to_date)s"
        params["to_date"] = filters["to_date"]

    return conditions, params

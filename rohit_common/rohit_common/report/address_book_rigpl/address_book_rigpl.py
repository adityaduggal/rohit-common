# Copyright (c) 2022, Rohit Industries Ltd. and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
import datetime
import urllib.parse
from frappe.utils import getdate
from ....utils.contact_utils import get_contact_phones, get_contact_emails


def execute(filters=None):
    conditions, tbl_join, fd_add, params = get_conditions(filters)
    data = get_entries(filters, conditions, tbl_join, fd_add, params)
    columns, data = get_columns(filters, data)

    return columns, data


def get_columns(filters, data):
    new_data = []
    if filters.get("type") == "Address":
        col_map = [
            {"fieldname": "name", "label": "Address Link", "fieldtype":"Link", "options":"Address", "width": 120},
            {"fieldname": "address_type", "label": "Address Type", "fieldtype":"Data", "width": 100},
            {"fieldname": "address_title", "label": "Address Title", "fieldtype":"Data", "width": 120},
            {"fieldname": "address_line1", "label": "Address Line1", "fieldtype":"Data", "width": 150},
            {"fieldname": "address_line2", "label": "Address Line2", "fieldtype":"Data", "width": 120},
            {"fieldname": "city", "label": "City", "fieldtype":"Data", "width": 100},
            {"fieldname": "state", "label": "State", "fieldtype":"Data", "width": 100},
            {"fieldname": "country", "label": "Country", "fieldtype":"Link", "options":"Country", "width": 100},
            {"fieldname": "airport", "label": "Airport", "fieldtype":"Data", "width": 100},
            {"fieldname": "sea_port", "label": "Sea Port", "fieldtype":"Data", "width": 100},
            {"fieldname": "email_id", "label": "Email", "fieldtype":"Data", "width": 150},
            {"fieldname": "phone", "label": "Phone", "fieldtype":"Data", "width": 120},
            {"fieldname": "fax", "label": "Fax", "fieldtype":"Data", "width": 100},
            {"fieldname": "gstin", "label": "GSTIN", "fieldtype":"Data", "width": 140},
            {"fieldname": "gst_status", "label": "GST Status", "fieldtype":"Data", "width": 100},
            {"fieldname": "gst_validation_date", "label": "Validation Date", "fieldtype":"Date", "width": 100},
            {"fieldname": "global_google_code", "label": "Google Code", "fieldtype":"Data", "width": 120},
            {"fieldname": "disabled", "label": "Disabled", "fieldtype":"Check", "width": 80},
            {"fieldname": "link_doctype", "label": "Master Type", "fieldtype":"Data", "width": 120},
            {"fieldname": "link_name", "label": "Master Name", "fieldtype":"Dynamic Link", "options":"link_doctype", "width": 120}
        ]
    else:
        col_map = [
            {"fieldname": "name", "label": "Contact Link", "fieldtype":"Link", "options":"Contact", "width": 120},
            {"fieldname": "salutation", "label": "Salutation", "fieldtype":"Data", "width": 100},
            {"fieldname": "first_name", "label": "First Name", "fieldtype":"Data", "width": 120},
            {"fieldname": "middle_name", "label": "Middle Name", "fieldtype":"Data", "width": 100},
            {"fieldname": "last_name", "label": "Last Name", "fieldtype":"Data", "width": 120},
            {"fieldname": "phone", "label": "Phone", "fieldtype":"Data", "width": 150},
            {"fieldname": "email", "label": "Email", "fieldtype":"Data", "width": 200},
            {"fieldname": "designation", "label": "Designation", "fieldtype":"Data", "width": 120},
            {"fieldname": "department", "label": "Department", "fieldtype":"Data", "width": 120},
            {"fieldname": "birthday", "label": "Birthday", "fieldtype":"Date", "width": 100},
            {"fieldname": "anniversary", "label": "Anniversary", "fieldtype":"Date", "width": 100},
            {"fieldname": "notes", "label": "Small Text", "fieldtype":"Small Text", "width": 150},
            {"fieldname": "is_primary_contact", "label": "Primary", "fieldtype":"Check", "width": 80},
            {"fieldname": "link_doctype", "label": "Master Type", "fieldtype":"Data", "width": 120},
            {"fieldname": "link_name", "label": "Master Name", "fieldtype":"Dynamic Link", "options":"link_doctype", "width": 120},
            {"fieldname": "gender", "label": "Gender", "fieldtype":"Data", "width": 100}
        ]
    
    if filters.get("customer_group"):
        col_map.append({"fieldname": "customer_group", "label": "Cust Group", "fieldtype":"Link", "options":"Customer Group", "width": 120})
    if filters.get("territory"):
        col_map.append({"fieldname": "territory", "label": "Territory", "fieldtype":"Link", "options":"Territory", "width": 120})
    
    if not data:
        return col_map, []

    # Efficient O(N) single-pass width and empty-column check
    max_lengths = {col["fieldname"]: 0 for col in col_map}
    for row in data:
        for col in col_map:
            val = row.get(col["fieldname"])
            if val:
                w = len(str(val))
                if w > max_lengths[col["fieldname"]]:
                    max_lengths[col["fieldname"]] = w

    # Filter out empty columns and update widths dynamically
    final_cols = []
    for col in col_map:
        mlen = max_lengths[col["fieldname"]]
        if mlen > 0:
            # Dynamically adjust width if content is longer than default
            calc_w = min(mlen * 10, 300)
            col["width"] = max(col.get("width", 100), calc_w)
            final_cols.append(col)

    # Build final data list efficiently based on filtered columns
    for row in data:
        new_data.append([row.get(col["fieldname"]) for col in final_cols])

    return final_cols, new_data


def get_entries(filters, conditions, tbl_join, fd_add, params):
    data = []
    if filters.get("type") == "Address":
        if filters.get("orphaned") != 1:
            query = f"""
                SELECT 
                    ad.name, ad.address_title, ad.address_type, ad.address_line1,
                    ad.address_line2, ad.city, ad.state, ad.country, ad.pincode, ad.sea_port, ad.airport,
                    ad.email_id, ad.phone, ad.fax, ad.gstin, ad.disabled, dl.link_doctype, dl.link_name,
                    ad.global_google_code, ad.gst_status, ad.gst_validation_date, ad.latitude, ad.longitude
                    {fd_add}
                FROM `tabAddress` ad
                INNER JOIN `tabDynamic Link` dl ON dl.parent = ad.name
                {tbl_join}
                WHERE dl.parenttype = 'Address' {conditions}
                ORDER BY dl.link_doctype, dl.link_name, ad.name
            """
        else:
            query = """
                SELECT 
                    ad.name, ad.address_title, ad.address_type, ad.address_line1,
                    ad.address_line2, ad.city, ad.state, ad.country, ad.pincode, ad.sea_port, ad.airport,
                    ad.email_id, ad.phone, ad.fax, ad.gstin, ad.disabled, ad.global_google_code,
                    ad.gst_status, ad.gst_validation_date
                FROM `tabAddress` ad
                WHERE ad.name NOT IN (SELECT parent FROM `tabDynamic Link` WHERE parenttype = 'Address' GROUP BY parent)
                ORDER BY ad.name
            """
    else:
        if filters.get("orphaned") != 1:
            query = f"""
                SELECT 
                    con.name,
                    COALESCE(NULLIF(TRIM(con.salutation), ''), 'zNo Salutation') as salutation,
                    COALESCE(NULLIF(TRIM(con.first_name), ''), 'zNo First Name') as first_name,
                    COALESCE(NULLIF(TRIM(con.middle_name), ''), 'zNo Middle Name') as middle_name,
                    COALESCE(NULLIF(TRIM(con.last_name), ''), 'zNo Last Name') as last_name,
                    COALESCE(NULLIF(TRIM(con.gender), ''), 'zNo Gender') as gender, 
                    con.is_primary_contact,
                    con.birthday, con.anniversary, con.designation, con.department, con.notes,
                    dl.link_doctype, dl.link_name {fd_add}
                FROM `tabContact` con
                INNER JOIN `tabDynamic Link` dl ON dl.parent = con.name
                {tbl_join}
                WHERE dl.parenttype = 'Contact' {conditions}
                ORDER BY dl.link_doctype, dl.link_name, con.name
            """
        else:
            query = """
                SELECT 
                    con.name,
                    COALESCE(NULLIF(TRIM(con.salutation), ''), 'zNo Salutation') as salutation,
                    COALESCE(NULLIF(TRIM(con.first_name), ''), 'zNo First Name') as first_name,
                    COALESCE(NULLIF(TRIM(con.middle_name), ''), 'zNo Middle Name') as middle_name,
                    COALESCE(NULLIF(TRIM(con.last_name), ''), 'zNo Last Name') as last_name,
                    COALESCE(NULLIF(TRIM(con.gender), ''), 'zNo Gender') as gender, 
                    con.is_primary_contact,
                    con.birthday, con.anniversary, con.designation, con.department, con.notes
                FROM `tabContact` con
                WHERE con.name NOT IN (SELECT parent FROM `tabDynamic Link` WHERE parenttype = 'Contact' GROUP BY parent)
                ORDER BY con.name
            """
    
    data = frappe.db.sql(query, params, as_dict=1)

    if filters.get("type") == "Contact" and data:
        contact_names = [r.name for r in data]
        
        # Optimized Bulk fetching for Phones
        phones = frappe.get_all("Contact Phone", filters={"parent": ["in", contact_names]}, fields=["parent", "phone"])
        phone_map = {}
        for p in phones:
            p_name = p.parent
            if p_name not in phone_map: phone_map[p_name] = []
            phone_map[p_name].append(p.phone)

        # Optimized Bulk fetching for Emails
        emails = frappe.get_all("Contact Email", filters={"parent": ["in", contact_names]}, fields=["parent", "email_id"])
        email_map = {}
        for e in emails:
            e_name = e.parent
            if e_name not in email_map: email_map[e_name] = []
            email_map[e_name].append(e.email_id)

        for row in data:
            row["phone"] = ", ".join(phone_map.get(row.name, []))
            row["email"] = ", ".join(email_map.get(row.name, []))
    
    return data


def get_conditions(filters):
    cond = ""
    tbl_join = ""
    fd_add = ""
    params = {}
    if filters.get("link_type"):
        cond += " AND dl.link_doctype = %(link_type)s"
        params["link_type"] = filters.get("link_type")

    if filters.get("linked_to"):
        cond += " AND dl.link_name = %(linked_to)s"
        params["linked_to"] = filters.get("linked_to")

    if filters.get("territory"):
        fd_add += ", cu.territory"
        if tbl_join == "":
            tbl_join += """ LEFT JOIN `tabCustomer` cu ON dl.link_doctype = 'Customer'
                AND dl.link_name = cu.name"""
        terr = frappe.get_doc("Territory", filters["territory"])
        if terr.is_group == 1:
            child_territories = frappe.get_all("Territory", filters={"lft": [">=", terr.lft], "rgt": ["<=", terr.rgt]}, pluck="name")
            cond += " AND cu.territory IN %(territories)s"
            params["territories"] = child_territories
        else:
            cond += " AND cu.territory = %(territory)s"
            params["territory"] = filters["territory"]

    if filters.get("customer_group"):
        fd_add += ", cu.customer_group"
        if "tabCustomer" not in tbl_join:
            tbl_join += """ LEFT JOIN `tabCustomer` cu ON dl.link_doctype = 'Customer'
                AND dl.link_name = cu.name"""
        cg = frappe.get_doc("Customer Group", filters["customer_group"])
        if cg.is_group == 1:
            child_cgs = frappe.get_all("Customer Group", filters={"lft": [">=", cg.lft], "rgt": ["<=", cg.rgt]}, pluck="name")
            cond += " AND cu.customer_group IN %(customer_groups)s"
            params["customer_groups"] = child_cgs
        else:
            cond += " AND cu.customer_group = %(customer_group)s"
            params["customer_group"] = filters["customer_group"]
    return cond, tbl_join, fd_add, params

@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_doctypes_with_field(doctype, txt, searchfield, start, page_len, filters):
    """
    Finds DocTypes that contain a specific fieldname and fieldtype.
    Searches both standard DocFields and Custom Fields.
    """
    fieldname = filters.get("fieldname")
    fieldtype = filters.get("fieldtype")

    standard_doctypes = frappe.get_all("DocField", 
        filters={
            "fieldname": fieldname, 
            "fieldtype": fieldtype, 
            "parent": ["like", f"%{txt}%"]
        },
        fields=["parent"], 
        distinct=1, 
        pluck="parent"
    )

    custom_doctypes = frappe.get_all("Custom Field", 
        filters={
            "fieldname": fieldname, 
            "fieldtype": fieldtype, 
            "dt": ["like", f"%{txt}%"]
        },
        fields=["dt"], 
        distinct=1, 
        pluck="dt"
    )
    
    results = sorted(list(set(standard_doctypes + custom_doctypes)))
    
    return [[r] for r in results]
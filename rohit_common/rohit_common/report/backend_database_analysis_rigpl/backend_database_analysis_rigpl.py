#  Copyright (c) 2021. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe.utils import flt
from frappe.model import core_doctypes_list
from ....patches.backend_table_analysis import get_size_of_all_tables, get_columns_of_all_tables


def execute(filters=None):
    """
    Executes a report
    """
    columns = get_columns(filters)
    data = get_data(filters)
    return columns, data


def get_columns(filters):
    """
    Returns the columns for the Report
    """
    get_conditions(filters)
    if filters.get("all_tables") == 1:
        return [
            {"label": "Database Name", "fieldname": "db_name", "fieldtype": "Data", "width": 150},
            {"label": "Table Name", "fieldname": "tbl_name", "fieldtype": "Data", "width": 250},
            {"label": "Size (MB)", "fieldname": "size_mb", "fieldtype": "Float", "width": 100},
            {"label": "Data (MB)", "fieldname": "dl_mb", "fieldtype": "Float", "width": 100},
            {"label": "Index (MB)", "fieldname": "ind_mb", "fieldtype": "Float", "width": 100},
            {"label": "Total Rows", "fieldname": "tbl_rows", "fieldtype": "Int", "width": 100},
            {"label": "Columns", "fieldname": "no_of_cols", "fieldtype": "Int", "width": 100}
        ]
    elif filters.get("unused_tables") == 1:
        return [
            {"label": "DB Name", "fieldname": "db_name", "fieldtype": "Data", "width": 150},
            {"label": "App", "fieldname": "app", "fieldtype": "Data", "width": 100},
            {"label": "Module", "fieldname": "module", "fieldtype": "Data", "width": 120},
            {"label": "Table Name", "fieldname": "tbl_name", "fieldtype": "Data", "width": 200},
            {"label": "Potential DT", "fieldname": "dt_name", "fieldtype": "Data", "width": 180},
            {"label": "Size (MB)", "fieldname": "size_mb", "fieldtype": "Float", "width": 100},
            {"label": "Last Entry", "fieldname": "last_entry", "fieldtype": "Datetime", "width": 180},
            {"label": "Total Rows", "fieldname": "tbl_rows", "fieldtype": "Int", "width": 100}
        ]
    else:
        return [
            {"label": "Database Name", "fieldname": "db_name", "fieldtype": "Data", "width": 150},
            {"label": "Table Name", "fieldname": "tbl_name", "fieldtype": "Data", "width": 300},
            {"label": "Total Columns", "fieldname": "no_of_cols", "fieldtype": "Int", "width": 120}
        ]


def get_data(filters):
    """
    Returns the data in list format for the report
    """
    from ....patches.backend_table_analysis import get_size_of_all_tables, get_columns_of_all_tables, get_orphaned_tables
    
    if filters.get("all_tables") == 1:
        data_dict = get_size_of_all_tables()
        return data_dict
        
    elif filters.get("unused_tables") == 1:
        # Identified tables that exist in DB but aren't registered DocTypes
        return get_orphaned_tables()
        
    else:
        return get_columns_of_all_tables()


def get_conditions(filters):
    """
    To get condiitons from filters
    """
    chk_bx = flt(filters.get("all_tables")) + \
        flt(filters.get("col_nos")) + flt(filters.get("unused_tables"))
    if chk_bx > 1 or chk_bx == 0:
        frappe.throw("Only 1 Checkbox is Allowed at a Time")

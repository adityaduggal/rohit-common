# Copyright (c) 2013, Rohit Industries Ltd. and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from ....utils.rohit_common_utils import get_folder_details


def execute(filters=None):
    columns = get_columns(filters)
    data = get_data(filters)
    return columns, data


def get_columns(filters):
    if filters.get("summary_dt") == 1:
        return ["Attached to Doctype::300", "No of Files:Int:100", "Size (MB):Float:100"]
    elif filters.get("summary_fol") == 1:
        return ["Folder Name:Link/File:300", "Parent Folder:Link/File:300", "No of Files:Int:100",
            "Actual Files Size (MB):Float:100", "Size Listed:Float:100", "Left:Int:80",
            "Right:Int:80", "Owner::120"]
    else:
        if filters.get("is_folder") == 1:
            return [
                "ID:Link/File:450", "File Name::200", "Parent Folder:Link/File:350", "Size(MB):Float:100",
                "Left:Int:80", "Right:Int:80", "Files:Int:80", "Is Home:Int:40", "Is Attachment::40",
                "Owner::80"
            ]
        else:
            return [
                "ID:Link/File:150", "File Name::200",
                {
                    "label": "Attached To DT",
                    "fieldname": "attached_to_dt",
                    "width": 100
                },
                {
                    "label": "Attached to Name",
                    "fieldname": "attached_to_name",
                    "fieldtype": "Dynamic Link",
                    "options": "attached_to_dt",
                    "width": 100
                },
                "Available:Int:50", "Size(kB):Float:100", "Left:Int:80", "Right:Int:80", "Parent Folder:Link/File:350",
                "Private:Int:40", "Imp:Int:40", "Del:Int:40", "Owner::150", "Created On:Datetime:150", "URL::300"
            ]


def get_data(filters):
    data = []
    conditions, cond_summary = get_conditions(filters)
    
    if filters.get("summary_dt") == 1:
        data = frappe.db.sql("""
            SELECT IFNULL(attached_to_doctype, "NO DOCTYPE"), COUNT(name) as no_of_files,
            ROUND(((SUM(file_size))/1024/1024),2) as size 
            FROM `tabFile` WHERE docstatus=0 AND is_folder=0 %s
            GROUP BY attached_to_doctype ORDER BY size DESC, no_of_files DESC 
        """ % cond_summary, as_list=1)
        
    elif filters.get("summary_fol") == 1:
        # Optimized joined query to get folder details and child file aggregate stats in one go
        new_data = frappe.db.sql("""
            SELECT 
                f.name, f.folder, 
                ROUND(f.file_size/1024/1024, 2) as size, 
                f.lft, f.rgt, f.owner,
                COALESCE(child_stats.nos, 0) as count,
                COALESCE(child_stats.size, 0) as act_size
            FROM `tabFile` f
            LEFT JOIN (
                SELECT folder, COUNT(name) as nos, ROUND(SUM(file_size)/1024/1024, 2) as size
                FROM `tabFile`
                WHERE is_folder = 0 AND docstatus = 0
                GROUP BY folder
            ) child_stats ON child_stats.folder = f.name
            WHERE f.docstatus=0 AND f.is_folder=1
            ORDER BY f.lft DESC, f.rgt DESC
        """, as_dict=1)
        
        for row in new_data:
            data_row = [row.name, row.folder, row.count, row.act_size, row.size, row.lft, row.rgt, row.owner]
            data.append(data_row)
            
    else:
        if filters.get("is_folder") == 1:
            data = frappe.db.sql("""
                SELECT name, file_name, folder, ROUND(file_size/1024/1024,2), lft, rgt, (rgt - lft),
                is_home_folder, is_attachments_folder, owner
                FROM `tabFile` WHERE docstatus = 0 %s ORDER BY lft, rgt
            """ % conditions, as_list=1)
        else:
            query = """
                SELECT 
                    name, IFNULL(file_name, "NO NAME") as file_name, 
                    IFNULL(attached_to_doctype, "NO DOCTYPE") as atd,
                    IFNULL(attached_to_name,"NO DOCNAME") as atn, 
                    file_available_on_server,
                    ROUND(file_size/1024, 2) as size, lft, rgt, 
                    IFNULL(folder, "NO FOLDER") as folder, is_private,
                    important_document_for_archive, mark_for_deletion, owner, creation, file_url
                FROM `tabFile` WHERE docstatus=0 %s ORDER BY creation
            """ % conditions
            
            fd_data = frappe.db.sql(query, as_dict=1)
            for d in fd_data:
                file_download_name = d.file_name
                file_download_url = d.file_url
                
                if d.file_url:
                    file_download_name = f'<a href="{d.file_url}" target="_blank">{d.file_name}</a>'
                    file_download_url = f'<a href="{d.file_url}" target="_blank">{d.file_url}</a>'
                    
                row = [
                    d.name, file_download_name, d.atd, d.atn, d.file_available_on_server, 
                    d.size, d.lft, d.rgt, d.folder, d.is_private, d.important_document_for_archive, 
                    d.mark_for_deletion, d.owner, d.creation, file_download_url
                ]
                data.append(row)
    return data


def get_conditions(filters):
    conditions = ""
    cond_summary = ""
    if filters.get("is_folder") == 1:
        conditions += " AND is_folder=1"
    else:
        conditions += " AND is_folder=0"

    if filters.get("private") == "Only Private":
        conditions += " AND is_private=1"
        cond_summary += " AND is_private=1"
    elif filters.get("private") == "Only Public":
        conditions += " AND is_private=0"
        cond_summary += " AND is_private=0"
    else:
        pass

    if filters.get("dt_types") != "None" and filters.get("doctype"):
        conditions += " AND attached_to_doctype = '%s'" % (filters.get("doctype"))
    elif filters.get("dt_types") == "None" and filters.get("doctype"):
        frappe.throw("None Doctype Selected and hence Cannot Select a Specific Doctype")

    if filters.get("dt_types") == "None":
        conditions += " AND attached_to_doctype IS NULL"

    if filters.get("folder"):
        folder_details = get_folder_details(filters.get("folder"))
        lft = folder_details[0].lft + 1
        rgt = folder_details[0].rgt - 1
        conditions += " AND lft >= %s AND rgt <= %s" % (lft, rgt)

    if filters.get("no_parent") == 1:
        conditions += " AND folder IS NULL"

    if filters.get("on_server") == "Yes":
        conditions += " AND file_available_on_server = 1"
        cond_summary += " AND file_available_on_server = 1"
    elif filters.get("on_server") == "No":
        conditions += " AND file_available_on_server = 0"
        cond_summary += " AND file_available_on_server = 0"

    if filters.get("deletion"):
        cond_summary += " AND mark_for_deletion = 1"
        conditions += " AND mark_for_deletion = 1"

    if filters.get("archive"):
        cond_summary += " AND important_document_for_archive = 1"
        conditions += " AND important_document_for_archive = 1"

    return conditions, cond_summary

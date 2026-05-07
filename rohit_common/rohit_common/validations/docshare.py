#  Copyright (c) 2021. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-

'''
Check sharing for Files and Folder if Folder is Shared it should share all subfolders and files
Also if Unsharing a folder then unshare all the sub-folders and files
Changing a folder sharing settings should change lower ones

'''

from __future__ import unicode_literals
import frappe
from frappe.utils.background_jobs import enqueue
from rohit_common.utils.rohit_common_utils import check_system_manager


def on_trash(doc, method):
    doc_childs = get_file_tree(doc.share_doctype, doc.share_name)
    if doc_childs:
        for chd in doc_childs:
            exists = frappe.db.exists("DocShare", {"owner":doc.owner, "share_doctype":doc.share_doctype, "share_name":chd.name})
            if exists:
                shared = frappe.get_doc("DocShare", exists)
                shared.delete()


def validate(doc, method):
    validate_duplicate(user=doc.user, dt=doc.share_doctype, dn=doc.share_name, ex_name=doc.name)
    check_create_more_ds(doc)


def validate_duplicate(user, dt, dn, ex_name):
    existing = frappe.db.sql("""SELECT name FROM `tabDocShare` WHERE user='%s' AND share_doctype='%s'
        AND share_name='%s' AND name != '%s' """ % (user, dt, dn, ex_name), as_dict=1)
    if existing:
        frappe.throw(f"There are {len(existing)} similar DocShares. Need to Delete them Before Proceeding")


def check_create_more_ds(doc):
    doc_childs = get_file_tree(doc.share_doctype, doc.share_name)
    # doc = frappe.get_doc(doctype="DocShare", filters={"share_doctype": share_doctype, "share_name":share_name, "user": user})
    if doc_childs:
        for chd in doc_childs:
            create_docshare_for_tree(doc, chd=chd)


def create_docshare_for_tree(doc, chd):
    dshare_args = {
        "owner": doc.owner,
        "user": doc.user,
        "dt": doc.share_doctype,
        "dn": chd.name,
        "read": doc.read,
        "write": doc.write,
        "share": doc.share,
        "ev_one": doc.everyone
    }
    create_docshare(user=doc.user, dt=doc.share_doctype, dn=chd.name,
        read=doc.read, write=doc.write, share=doc.share, ev_one=doc.everyone)
    # enqueue(method=create_docshare, queue="short", timeout=300, **dshare_args)


def get_file_tree(share_doctype, share_name):
    doc_childs = []
    if share_doctype == 'File':
        file_dt = frappe.get_value("File", share_name, fieldname=["is_folder", "lft", "rgt", "folder", "name"],as_dict=1)
        if file_dt and file_dt.is_folder == 1:
            doc_childs = frappe.db.sql("""SELECT name, is_folder, lft, rgt, folder FROM `tabFile`
                WHERE lft > %s AND rgt < %s""" % (file_dt.lft, file_dt.rgt), as_dict=1)
    return doc_childs


def get_docshare_from_dt(dt, user):
    docshares = []
    if dt.doctype == 'File':
        docshares = frappe.db.get_values("DocShare", filters={"user": user, "share_doctype":dt.doctype,
            "share_name": dt.name}, as_dict=1)
    return docshares


def create_docshare(user, dt, dn, read=0, write=0, share=0, ev_one=0, subm=0,
    change_exist=0):
    """
    Dont Create DocShares for Admin, Guest or System Managers
    """
    shared_dts = ["User", "Event", "Note"]
    share_needed = 1
    existing_share = frappe.db.exists("DocShare", {"share_doctype": dt, "user": user, "share_name": dn})
    is_sys = check_system_manager(user)
    if (is_sys or user == "Administrator") and (dt not in shared_dts and dn != user):
        share_needed = 0
        frappe.throw("NO SHARE NEEDED")
    if share_needed == 1:
        if not existing_share:
            dc = frappe.new_doc("DocShare")
            dc.user = user
            dc.share_doctype = dt
            dc.share_name = dn
            dc.read = read
            dc.write = write
            dc.share = share
            dc.everyone = ev_one
            dc.submit = subm
            dc.notify_by_email = 0
            # print(dc.name)
            dc.insert()
            dc.save()
        else:
            exist_dc = frappe.get_doc("DocShare", {"share_doctype": dt, "user": user, "share_name": dn})
            exist_dc.read = read
            exist_dc.write = write
            exist_dc.share = share
            exist_dc.everyone = ev_one
            exist_dc.submit = subm
            exist_dc.notify_by_email = 0
            exist_dc.save()
    else:
        if existing_share:
            exist_dc = frappe.get_doc("DocShare", {"share_doctype": dt, "user": user, "share_name": dn})
            exist_dc.flags.ignore_permissions = 1
            exist_dc.delete_doc(delete_permanently=1)


def delete_docshare(docname):
    frappe.delete_doc("DocShare", docname)

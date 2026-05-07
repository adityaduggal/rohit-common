# -*- coding: utf-8 -*-
# Copyright (c) 2020, Rohit Industries Group Pvt Ltd. and contributors
# For license information, please see license.txt

# This Manual Patch would list all the public and private files if the files are not in the DB `tabFiles`
# then it would delete them.


from __future__ import unicode_literals
import frappe
import time
import os
from os import listdir
from os.path import isfile, join
from pathlib import Path
from frappe.utils import get_files_path


def execute():
    delete_file = input("Do You Really Want to Delete Files Enter y or n: ")
    if delete_file == "y" or delete_file == "n":
        pass
    else:
        frappe.throw("Wrong Input Enter either y or n. y = If you want to delete files and n = If you only want a list of orphaned files at the end of this patch")
        # print("Wrong Input Enter either y or n. y = If you want to delete files and n = If you only want a list of "
        #       "orphaned files at the end of this patch")
        # exit()
        return
    st_time = time.time()
    public_files_path = get_files_path()
    private_files_path = get_files_path(is_private=1)
    public_files = [f for f in listdir(public_files_path) if isfile(join(public_files_path, f))]
    private_files = [f for f in listdir(private_files_path) if isfile(join(private_files_path, f))]
    orphan_private = 0
    orp_priv_size = 0
    orphan_pub = 0
    orp_pub_size = 0
    counting = 0
    deleted_file_list = []
    for list_of_files in [public_files, private_files]:
        if list_of_files:
            for files in list_of_files:
                counting += 1
                if counting % 500 == 0 and counting > 0:
                    print(f"Total Files Checked = {counting}. Time Elapsed = {int(time.time() - st_time)} seconds")
                if '"' in files:
                    file_wild_card = '%' + files + '%'
                else:
                    file_wild_card = "%" + files + "%"
                if list_of_files == public_files:
                    file_path = public_files_path + '/' + files
                    file_url = '/files/' + files
                else:
                    file_path = private_files_path + '/' + files
                    file_url = '/private/files/' + files
                if '"' in files:
                    query = """SELECT name, attached_to_doctype, attached_to_name, file_url, file_name 
                    FROM `tabFile` WHERE  (file_name = '%s' OR file_url = '%s' 
                    OR file_url LIKE '%s') """ % (files, file_url, file_wild_card)
                else:
                    query = """SELECT name, attached_to_doctype, attached_to_name, file_url, file_name
                    FROM `tabFile` WHERE  (file_name = "%s" OR file_url = "%s" 
                    OR file_url LIKE "%s") """ % (files, file_url, file_wild_card)
                file_db = frappe.db.sql(query, as_list=1)
                if file_db:
                    pass
                # print(file_db)
                else:
                    file_size_kb = round(Path(file_path).stat().st_size / 1024, 2)
                    print(f"Deleted file with Size = {file_size_kb} kB and Name = {files} and file path = {file_path}")
                    if list_of_files == public_files:
                        orphan_pub += 1
                        orp_pub_size += Path(file_path).stat().st_size
                    else:
                        orphan_private += 1
                        orp_priv_size += Path(file_path).stat().st_size
                    if delete_file == "y":
                        os.remove(file_path)
                    deleted_file_list.append(file_path)
    tot_time = int(time.time() - st_time)
    tot_pub_size = round(orp_pub_size / 1024 / 1024, 2)
    tot_priv_size = round(orp_priv_size / 1024 / 1024, 2)

    print(f"Total Public Files = {len(public_files)}")
    print(f"Total Private Files = {len(private_files)}")
    print(f"Public Files Orphaned and hence Deleted = {orphan_pub} with Total = {tot_pub_size} MB")
    print(f"Private Files Orphaned and hence Deleted = {orphan_private} with Total Size = {tot_priv_size} MB")
    print(f"Total Time Taken = {tot_time} seconds")
    print(f"{deleted_file_list}")

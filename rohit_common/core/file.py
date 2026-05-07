# Copyright (c) 2022 Rohit Industries Group Private Limited and Contributors.
# For license information, please see license.txt
# -*- coding: utf-8 -*-

from __future__ import unicode_literals
import os
import frappe
from shutil import copyfile, move
from frappe.permissions import SYSTEM_USER_ROLE, get_doctypes_with_read
from frappe.share import get_share_name
from frappe.utils import get_site_base_path, cstr
from frappe.core.doctype.file.file import File, get_content_hash
from rohit_common.utils.rohit_common_utils import check_system_manager
from pathlib import Path


def custom_file_permissions(doc, ptype=None, user=None):
    """
    This would resolve the problem when a private file is not attached to any doctype
    then its allowed if shared or if the person is owner or system manager AND
    Administrator has full access
    """
    has_access = False
    user = user or frappe.session.user
    is_sys = check_system_manager(user)

    # System Manager & Administrator always get full access
    if user == "Administrator" or is_sys:
        return True

    # Check if shared
    shd_name = get_share_name(doctype=doc.doctype, name=doc.name, user=user, everyone=0)
    if shd_name:
        shd = frappe.get_doc("DocShare", shd_name)
        if shd.write or shd.share or shd.submit:
            return True
        return True

    # Creating a new file
    if ptype == "create":
        return frappe.has_permission("File", "create", user=user)

    # Public file or owner
    if not doc.is_private or doc.owner in [user, "Guest"]:
        return True

    # If attached → check permission on parent doc
    if doc.attached_to_doctype and doc.attached_to_name:
        try:
            ref_doc = frappe.get_doc(doc.attached_to_doctype, doc.attached_to_name)
            if ptype in ["write", "create", "delete"]:
                has_access = ref_doc.has_permission("write")
                if ptype == "delete" and not has_access:
                    frappe.throw(
                        (
                            f"Cannot delete file as it belongs to {frappe.get_desk_link(doc.attached_to_doctype, doc.attached_to_name)} for which you do not have permissions"
                        ),
                        frappe.PermissionError,
                    )
            else:
                has_access = ref_doc.has_permission("read")
        except frappe.DoesNotExistError:
            # if parent doc is not created before file is created
            # we cannot check its permission so we will use file's permission
            pass

    return has_access

def custom_get_permission_query_conditions(user: str | None = None) -> str:
	user = user or frappe.session.user

	if user == "Administrator" or check_system_manager(user):
		return ""

	if SYSTEM_USER_ROLE not in frappe.get_roles(user):
		# Basic user: return only own files or shared
		return f"""
			`tabFile`.`owner` = {frappe.db.escape(user)}
			OR EXISTS (
				SELECT 1 FROM `tabDocShare`
				WHERE
					`tabDocShare`.share_doctype = 'File'
					AND `tabDocShare`.share_name = `tabFile`.name
					AND `tabDocShare`.user = {frappe.db.escape(user)}
					AND `tabDocShare`.read = 1
			)
		"""

	# For system users, include additional readable doctypes and shares
	readable_doctypes = ", ".join(repr(dt) for dt in get_doctypes_with_read())
	return f"""
		(`tabFile`.`is_private` = 0)
		OR (`tabFile`.`attached_to_doctype` IS NULL AND `tabFile`.`owner` = {frappe.db.escape(user)})
		OR (`tabFile`.`attached_to_doctype` IN ({readable_doctypes}))
		OR EXISTS (
			SELECT 1 FROM `tabDocShare`
			WHERE
				`tabDocShare`.share_doctype = 'File'
				AND `tabDocShare`.share_name = `tabFile`.name
				AND `tabDocShare`.user = {frappe.db.escape(user)}
				AND `tabDocShare`.read = 1
		)
	"""

@frappe.whitelist()
def get_files_by_search_text(text):
    """
    This function seems similar to the one by frappe but here is a big difference
    Here if you do add a field in customized form view to the search then you can
    search the files by that fields as well so here the docname of the attached field
    when entered in the customize form view in search fields wee can easily
    search the files.
    """
    file_meta = frappe.get_meta(doctype="File")
    search_flds = file_meta.get_search_fields()
    std_flds = ["name", "file_name", "file_url", "modified"]
    if not text:
        return []
    text = "%" + cstr(text).lower() + "%"
    for fld in search_flds:
        if fld not in std_flds:
            std_flds.append(fld)
    or_filters = []
    for fld in search_flds:
        or_filters.append([f"{fld}", "LIKE", f"{text}"])
    fl_lst = frappe.db.get_list(doctype="File", fields=search_flds,
                                filters={"is_folder": 0},
                                or_filters=or_filters, order_by="modified")
    return fl_lst

def on_trash(doc, method):
    if doc.important_document_for_archive == 1:
        frappe.throw(f"{doc.name} is Checked for Archive hence Cannot be Deleted")


def before_insert(doc, method):
    validate_folder(doc)
    check_public_allowed(doc)


def validate(doc, method):
    if doc.mark_for_deletion == 1 and doc.important_document_for_archive == 1:
        frappe.throw(f"{doc.name} Cannot be Marked for Deletion as its an Important Document")
    check_and_move_file(doc)
    get_size(doc)
    folder_related_jobs(doc)


def folder_related_jobs(doc):
    fd_doc = frappe.get_doc('File', doc.folder)
    if fd_doc.important_document_for_archive == 1:
        doc.important_document_for_archive = 1
    if fd_doc.mark_for_deletion == 1:
        doc.mark_for_deletion = 1



def validate_folder(doc):
    # If the folder is empty then it would send to attachments folder
    home_folder = frappe.db.get_value("File", {"is_home_folder": 1})
    att_folder = frappe.db.get_value("File", {"is_attachments_folder": 1})
    if not doc.is_home_folder and (doc.folder == home_folder or not doc.folder) and not doc.flags.ignore_folder_validate:
        doc.folder = att_folder


def check_and_move_file(doc):
    # Check if public file then if its in private folder then move from Private folder if the Public File is allowed
    # If its a private file but available in Public Folder then copy the file to Private Folder
    in_private = 0
    in_public = 0
    file_available = check_file_availability(doc)
    rset = frappe.get_doc("Rohit Settings")
    if doc.is_private != 1 and file_available == 2:
        file_url = "/private/files/" + doc.file_name
        old_full_path = get_site_base_path() + "/public" + doc.file_url
        full_file_path = get_site_base_path() + file_url
        if doc.attached_to_doctype:
            dt_allowed = 0
            # Check if the Doctype is Allowed for Public Attachments if allowed then move the file to Public
            # Also make sure that file is not attached to another file if so all are public then move otherwise copy
            for row in rset.docs_with_pub_att:
                if doc.attached_to_doctype == row.document_type:
                    dt_allowed = 1
                    break
            if dt_allowed == 1:
                other_files = frappe.db.sql("""SELECT name, is_private FROM `tabFile`
                WHERE file_name = '%s' AND name != '%s'""" % (doc.file_name, doc.name), as_dict=1)
                # frappe.msgprint(f"Same File Name attached to {str(len(other_files))} more files")
                for file in other_files:
                    if file.is_private == 1:
                        # File exists in both Private and Public
                        in_private = 1
                        break
                if in_private == 1:
                    # Copy the file from Private to Public
                    copyfile(old_full_path, full_file_path)
                    frappe.msgprint(f"Copying file {doc.file_name} from {old_full_path} to {full_file_path}")
                    print(f"Copying file {doc.file_name} from {old_full_path} to {full_file_path}")
                else:
                    # Move the file from Private to Public since all files are Public
                    move(full_file_path, old_full_path)
                    frappe.msgprint(f"Would Move the File From {full_file_path} to {old_full_path}")
                    print(f"Would Move the File From {full_file_path} to {old_full_path}")
            else:
                # Doctype is not allowed to have public files so make it Private
                frappe.msgprint(f"Convert {doc.name} from Public to Private via DB Call")
                print(f"Convert {doc.name} from Public to Private via DB Call")
                change_file_path(doc)
        else:
            # File attahcment not attached to any doctype so if its not there in any private file move else copy
            other_files = frappe.db.sql("""SELECT name, is_private FROM `tabFile`
            WHERE file_name = '%s' AND name != '%s'""" % (doc.file_name, doc.name), as_dict=1)
            for file in other_files:
                if file.is_private == 1:
                    # File exists in both private and public
                    in_private = 1
                    break
            if in_private == 1:
                # Copy the file from Private to Public
                copyfile(full_file_path, old_full_path)
                frappe.msgprint(f"Copying file {doc.file_name} from {old_full_path} to {full_file_path}")
                print(f"Copying file {doc.file_name} from {old_full_path} to {full_file_path}")
            else:
                # Move the file from Private to Public since all files are Public
                move(full_file_path, old_full_path)
                frappe.msgprint(f"Would Move the File From {full_file_path} to {old_full_path}")
                print(f"Would Move the File From {full_file_path} to {old_full_path}")
    elif doc.is_private == 1 and file_available == 2:
        file_url = "/public/files/" + doc.file_name
        old_full_path = get_site_base_path() + doc.file_url
        full_file_path = get_site_base_path() + file_url
        other_files = frappe.db.sql("""SELECT name, is_private FROM `tabFile` WHERE file_name = '%s'
        AND name != '%s'""" % (doc.file_name, doc.name), as_dict=1)
        for file in other_files:
            if file.is_private == 0:
                in_public = 1
                break
        if in_public == 1:
            copyfile(old_full_path, full_file_path)
            frappe.msgprint(f"Copying file {doc.file_name} from {old_full_path} to {full_file_path}")
            print(f"Copying file {doc.file_name} from {old_full_path} to {full_file_path}")
        else:
            move(full_file_path, old_full_path)
            frappe.msgprint(f"Would Move the File From {full_file_path} to {old_full_path}")
            print(f"Would Move the File From {full_file_path} to {old_full_path}")


def check_public_allowed(doc):
    # Check if File is Private or Public Only incase of Public Check rules
    # If Attached to Doctype then check 2 things if Role is Allowed and If Dt is Allowed
    # If not attached to DT then check if role is allowed or not if not then TRHOW
    doc_allowed, role_allowed = get_public_allowed(doc)
    if doc_allowed == 1 and role_allowed == 1:
        pass
    else:
        if role_allowed != 1:
            # Convert the Public File to Private and Store in Private Folder
            doc.is_private = 1
            doc.file_url = "/private/files/" + doc.file_name
            frappe.msgprint(f"Converted {doc.file_name} to Private Since {frappe.session.user} is "
                f"Not Allowed to Create Public Files")
        elif doc_allowed != 1:
            doc.is_private = 1
            doc.file_url = "/private/files/" + doc.file_name
            frappe.msgprint(f"Converted {doc.file_name} to Private Since {doc.attached_to_doctype} "
                f"is Not Allowed in Rohit Settings for Public Attachments.<br>To Create a Public "
                f"first Add {doc.attached_to_doctype} in Rohit Settings and then Attach Again")
        else:
            frappe.throw(f"Condition Undefined for File Attachments")


def get_public_allowed(doc):
    rset = frappe.get_doc("Rohit Settings")
    doc_allowed, role_allowed = 0, 0
    user_roles = frappe.get_roles(frappe.session.user)
    if doc.is_private == 1:
        doc_allowed = 1
        role_allowed = 1
    else:
        # Check if Role is allowed in Settings
        for role in rset.roles_allow_pub_att:
            if role.role in user_roles:
                role_allowed = 1
                break
        # If file is attached to DT then check else return allowed=1
        if doc.attached_to_doctype:
            for dt in rset.docs_with_pub_att:
                if doc.attached_to_doctype == dt.document_type:
                    doc_allowed = 1
                    break
        else:
            doc_allowed = 1
    return doc_allowed, role_allowed




def get_size(doc):
    file_path = get_file_path_from_doc(doc)
    if doc.file_available_on_server == 1:
        if Path(file_path).stat().st_size != doc.file_size:
            doc.file_size = Path(file_path).stat().st_size
    '''
    doc.flags.ignore_permissions = True
    if doc.is_folder == 1:
        files = frappe.db.sql("""SELECT name, size FROM `tabFile` WHERE lft > %s
        AND rgt < %s""" % (doc.lft, doc.rgt), as_dict=1)
        print(files)
    '''


def check_file_name(file_doc):
    disallowed_chars = ["'", '"']
    for d in disallowed_chars:
        if d in file_doc.file_name:
            frappe.throw(f"Illegal Character in File Name {file_doc.file_name}. "
                         "Please change and remove the illegal character from the file name to Proceed.")


def check_file_availability(file_doc, backend=0):
    # Validate File available on Server
    full_path = get_file_path_from_doc(file_doc)
    if file_doc.is_folder != 1:
        if os.path.exists(full_path):
            file_doc.file_available_on_server = 1
            if backend == 1:
                print(f"{file_doc.name} is Available on Server and Status Updated")
            return 1
        else:
            # File is not existing check if its in Private Folder with same name and content hash then change the
            # link for the link and update
            if file_doc.is_private != 1:
                if file_doc.file_name:
                    new_file_url = "/private/files/" + file_doc.file_name
                    full_path = get_site_base_path() + new_file_url
                    if os.path.exists(full_path):
                        # Check the content hash
                        with open(full_path, "rb") as f:
                            new_hash = get_content_hash(f.read())
                            if new_hash == file_doc.content_hash:
                                print(f"File {file_doc.name} Found in Private Files hence Changing")
                                return 2
                            else:
                                file_doc.file_available_on_server = 0
                                if backend == 0:
                                    frappe.msgprint(f"{file_doc.file_name} is Not Available as Hash Not Matched")
                                else:
                                    print(f"{file_doc.file_name} is Not Available as Hash Not Matched")
                                    return 0
                    else:
                        file_doc.file_available_on_server = 0
                        return 0
            else:
                if file_doc.file_name:
                    new_file_url = "/public/files/" + file_doc.file_name
                    full_path = get_site_base_path() + new_file_url
                    if os.path.exists(full_path):
                        # Check the content hash
                        with open(full_path, "rb") as f:
                            new_hash = get_content_hash(f.read())
                            if new_hash == file_doc.content_hash:
                                print(f"File {file_doc.name} Found in Public Files hence Changing")
                                return 2
                            else:
                                file_doc.file_available_on_server = 0
                                if backend == 0:
                                    frappe.msgprint(f"{file_doc.file_name} is Not Available as Has Not Matched")
                                else:
                                    print(f"{file_doc.file_name} is Not Available as Has Not Matched")
                                    return 0
                    else:
                        file_doc.file_available_on_server = 0
                        return 0


def get_file_path_from_doc(file_doc):
    file_in_private = 0
    if file_doc.file_url:
        if "http" in file_doc.file_url:
            file_name = (file_doc.file_url).rsplit("/", 1)[-1]
            # Check file_name in Both Public and Private files and if found change the URL and File Name
            file_in_private = file_name_exists(file_name, is_private=1)
            if file_in_private == 1:
                file_url = "/private/files/" + file_name
            else:
                file_in_public = file_name_exists(file_name)
                if file_in_public == 1:
                    file_in_private = 0
                    file_url = "/files/" + file_name
                else:
                    # Keep the file URL same as that earlier
                    file_url = file_doc.file_url
            file_doc.is_private = file_in_private
            file_doc.file_name = file_name
            file_doc.file_url = file_url
        elif file_doc.file_url[0] != "/":
            file_url = "/" + file_doc.file_url
            file_doc.file_url = file_url
        if file_doc.is_private == 1:
            full_path = get_site_base_path() + file_doc.file_url
        else:
            full_path = get_site_base_path() + "/public" + file_doc.file_url
    else:
        # Assumes if there is no file URL then it would be the file URL in File Name
        full_path = get_site_base_path() + file_doc.file_name
    return full_path


def check_other_files_with_same_file(fd):
    if fd.file_url:
        other_file = frappe.db.sql("""SELECT name FROM `tabFile` WHERE file_url = '%s' AND name != '%s'""" %
                                   (fd.file_url, fd.name))
        if other_file:
            return 1
        else:
            if fd.file_name:
                url_like = "%" + fd.file_name + "%"
                other_file = frappe.db.sql("""SELECT name FROM `tabFile` WHERE file_url LIKE '%s' AND name != '%s'"""
                                           % (url_like, fd.name))
                if other_file:
                    return 1
                else:
                    return 0
            else:
                return 0


def file_name_exists(file_name, is_private=0):
    if is_private == 1:
        full_path = get_site_base_path() + "/private/files/" + file_name
    else:
        full_path = get_site_base_path() + "/public/files/" + file_name

    if os.path.exists(full_path):
        return 1
    else:
        return 0


def delete_file_dt(fd, comment=None, ref_doc_exists=1):
    # fd = File doctype
    if fd.important_document_for_archive == 1:
        # Don't delete Files which are marked for archives
        pass
    else:
        # Check if File Available on server basically search for file name in Private and Public Files
        # if Found then change the link also check if file is there in another file data
        if fd.file_available_on_server == 1:
            # File available on Server and now check if the file is not present in another file databases
            other_files = check_other_files_with_same_file(fd)
            if other_files == 1:
                # Delete only the File Doc and not the actual file
                print(f"Only Deleting the File Doc {fd.name} and not the Actual File")
                delete_only_file_doc(fd, comment=comment, ref_doc_exists=ref_doc_exists)
            else:
                # Delete the file doc and also the actual file on the server
                print(f"Deleting the File Doc {fd.name} and Also the File")
                delete_only_file_doc(fd, comment=comment, ref_doc_exists=ref_doc_exists)
                full_path = get_file_path_from_doc(fd)
                try:
                    os.remove(path=full_path)
                except:
                    print(f"Unable to Remove the Actual File at {full_path}")
        else:
            file_available = check_file_availability(fd)
            if file_available == 1:
                fd.file_available_on_server = 1
                other_files = check_other_files_with_same_file(fd)
                if other_files:
                    print(f"Only Deleting the File Doc {fd.name} and not the Actual File Found in 2nd Attempt")
                    delete_only_file_doc(fd, comment=comment, ref_doc_exists=ref_doc_exists)
                else:
                    print(f"Deleting the File Doc {fd.name} and Also the File")
                    delete_only_file_doc(fd, comment=comment, ref_doc_exists=ref_doc_exists)
                    full_path = get_file_path_from_doc(fd)
                    os.remove(path=full_path)
            elif file_available == 2:
                check_and_move_file(fd)
            else:
                delete_only_file_doc(fd, comment=comment, ref_doc_exists=ref_doc_exists)


def correct_file_name_url(fd):
    is_private = 0
    if fd.file_name and not fd.file_url:
        # Correct the File URL based on availability and also change the private etc
        # Assume that the file name is the URL of the file on the server
        full_path = get_site_base_path() + fd.file_name
        if "/private/files/" in fd.file_name:
            is_private = 1
        if os.path.exists(full_path) == 1:
            frappe.db.set_value("File", fd.name, "is_private", is_private)
            frappe.db.set_value("File", fd.name, "file_available_on_server", 1)
            frappe.db.set_value("File", fd.name, "file_url", fd.file_name)
            frappe.db.set_value("File", fd.name, "file_name", fd.file_name.split("/")[-1])
        else:
            frappe.delete_doc("File", fd.name)
            print(f"{fd.name} is Not Available and does not have a File URL. Basing on the File Name Which "
                  f"does not Exists")
    elif fd.file_url and not fd.file_name:
        # Correct the File Name based on availability and also change the private etc
        file_available = check_file_availability(fd)
        if "/private/files/" in fd.file_url:
            is_private = 1
        if file_available == 1:
            frappe.db.set_value("File", fd.name, "is_private", is_private)
            frappe.db.set_value("File", fd.name, "file_available_on_server", 1)
            frappe.db.set_value("File", fd.name, "file_name", fd.file_url.split("/")[-1])
    elif fd.file_name:
        file_available = check_file_availability(fd)
        if file_available == 1:
            if fd.is_private == 1:
                file_url = "/private/files/" + fd.file_name
                frappe.db.set_value("File", fd.name, "file_url", file_url)
                frappe.db.set_value("File", fd.name, "file_available_on_server", 1)
            else:
                file_url = "/files/" + fd.file_name
                frappe.db.set_value("File", fd.name, "file_url", file_url)
                frappe.db.set_value("File", fd.name, "file_available_on_server", 1)
        else:
            print(f"File name there Checking File Availability = {file_available} for {fd.name}")
            frappe.delete_doc("File", fd.name, delete_permanently=1)
    elif fd.file_url:
        file_available = check_file_availability(fd)
        print(f"File URL there Checking File Availability = {file_available}")
        frappe.delete_doc("File", fd.name, delete_permanently=1)
    else:
        frappe.delete_doc("File", fd.name, delete_permanently=1)
        print(f"{fd.name} is Not in Condition and hence deleted")


def change_file_path(fd):
    print(f"Changing File Path for {fd.name}")
    if fd.file_name:
        # This is a condition when file is available on another folder like Private File actually in Public Folder
        # or vice-versa
        if fd.is_private == 1:
            file_path = "/files/" + fd.file_name
            frappe.db.set_value("File", fd.name, "file_url", file_path)
            frappe.db.set_value("File", fd.name, "file_available_on_server", 1)
            frappe.db.set_value("File", fd.name, "is_private", 0)
        else:
            file_path = "/private/files/" + fd.file_name
            frappe.db.set_value("File", fd.name, "file_url", file_path)
            frappe.db.set_value("File", fd.name, "file_available_on_server", 1)
            frappe.db.set_value("File", fd.name, "is_private", 1)
    else:
        frappe.throw("File Name is Not There hence Exiting")
        return
        # print("File Name is Not There hence Exiting")
        # exit()


def delete_only_file_doc(fd, comment=None, ref_doc_exists=1):
    if fd.attached_to_doctype and fd.attached_to_name and comment is not None and ref_doc_exists==1:
        dt = frappe.get_doc(fd.attached_to_doctype, fd.attached_to_name)
        dt.add_comment("Attachment Removed", comment)
    frappe.delete_doc("File", fd.name, for_reload=1, ignore_permissions=1)

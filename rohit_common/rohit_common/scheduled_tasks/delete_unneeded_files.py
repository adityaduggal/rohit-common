# -*- coding: utf-8 -*-
# Copyright (c) 2020, Rohit Industries Group Pvt Ltd. and contributors
# For license information, please see license.txt

# This Scheduled Tasks Would check all files marked for Deletion and Delete them.
# It would also check the files which are attached to some doctypes which need to be deleted as per deletion policy

from __future__ import unicode_literals
import time
import frappe
from frappe.utils import flt,add_days
from frappe.utils.fixtures import sync_fixtures
from ...utils.rohit_common_utils import rebuild_tree
from rohit_common.core.file import check_file_availability, delete_file_dt, check_and_move_file, correct_file_name_url

sync_fixtures()

def execute():
    log = frappe.logger("file_cleanup")
    
    BATCH_SIZE = 500
    start = time.time()

    # ------------------------------------------------
    # 1 Delete invalid files (no name + no url)
    # ------------------------------------------------

    rows = frappe.db.sql(
        """
        SELECT name
        FROM `tabFile`
        WHERE file_name IS NULL
        AND file_url IS NULL
        """,
        as_dict=True,
    )

    log.info(f"Deleting {len(rows)} files without name/url")

    for i, r in enumerate(rows, 1):

        fd = frappe.get_doc("File", r.name)
        delete_file_dt(fd)

        if i % BATCH_SIZE == 0:
            frappe.db.commit()

    frappe.db.commit()

    # ------------------------------------------------
    # 2 Fix missing file_name
    # ------------------------------------------------

    rows = frappe.db.sql(
        """
        SELECT name
        FROM `tabFile`
        WHERE file_name IS NULL
        AND is_folder = 0
        """,
        as_dict=True,
    )

    log.info(f"Fixing {len(rows)} files missing file_name")

    for r in rows:
        fd = frappe.get_doc("File", r.name)
        correct_file_name_url(fd)

    frappe.db.commit()

    # ------------------------------------------------
    # 3 Fix missing file_url
    # ------------------------------------------------

    rows = frappe.db.sql(
        """
        SELECT name
        FROM `tabFile`
        WHERE file_url IS NULL
        AND is_folder = 0
        """,
        as_dict=True,
    )

    log.info(f"Fixing {len(rows)} files missing file_url")

    for r in rows:
        fd = frappe.get_doc("File", r.name)
        correct_file_name_url(fd)

    frappe.db.commit()

    # ------------------------------------------------
    # 4 Fix http URLs
    # ------------------------------------------------

    rows = frappe.db.sql(
        """
        SELECT name
        FROM `tabFile`
        WHERE is_folder = 0
        AND (file_url LIKE 'http://%' OR file_url LIKE 'https://%')
        """,
        as_dict=True,
    )

    log.info(f"Fixing {len(rows)} http URL files")

    for r in rows:
        fd = frappe.get_doc("File", r.name)
        correct_file_name_url(fd)

    frappe.db.commit()

    # ------------------------------------------------
    # 5 Archive folders
    # ------------------------------------------------

    folders = frappe.db.sql(
        """
        SELECT name, lft, rgt
        FROM `tabFile`
        WHERE is_folder = 1
        AND important_document_for_archive = 1
        AND is_home_folder = 0
        AND is_attachments_folder = 0
        """,
        as_dict=True,
    )

    for folder in folders:

        log.info(f"Archiving subtree under folder {folder.name}")

        files = frappe.db.sql(
            """
            SELECT name
            FROM `tabFile`
            WHERE rgt <= %s
            AND lft >= %s
            AND important_document_for_archive = 0
            """,
            (folder.rgt, folder.lft),
            as_dict=True,
        )

        for f in files:
            frappe.db.set_value(
                "File",
                f.name,
                "important_document_for_archive",
                1,
            )

    frappe.db.commit()

    # ------------------------------------------------
    # 6 Delete files marked for deletion
    # ------------------------------------------------

    rows = frappe.db.sql(
        """
        SELECT name
        FROM `tabFile`
        WHERE mark_for_deletion = 1
        """,
        as_dict=True,
    )

    log.info(f"Deleting {len(rows)} files marked for deletion")

    for i, r in enumerate(rows, 1):

        fd = frappe.get_doc("File", r.name)

        delete_file_dt(
            fd,
            comment=f"Removed {r.name} as it was marked for deletion",
        )

        if i % BATCH_SIZE == 0:
            frappe.db.commit()

    frappe.db.commit()

    # ------------------------------------------------
    # 7 Auto deletion policy
    # ------------------------------------------------

    settings = frappe.get_single("Rohit Settings")

    # Cache allowed public doctypes
    allowed_public = {d.document_type for d in settings.docs_with_pub_att}

    total_auto_deleted = 0

    for row in settings.auto_deletion_policy_for_files:

        cutoff = add_days(frappe.utils.nowdate(), -int(row.days_to_keep))

        query = f"""
        SELECT fd.name
        FROM `tabFile` fd
        JOIN `tab{row.document_type}` dt
        ON dt.name = fd.attached_to_name
        WHERE fd.attached_to_doctype = %s
        AND fd.creation <= %s
        """

        if row.doctype_conditions:
            query += f" AND {row.doctype_conditions}"

        rows = frappe.db.sql(
            query,
            (row.document_type, cutoff),
            as_dict=True,
        )

        for i, r in enumerate(rows, 1):

            fd = frappe.get_doc("File", r.name)

            delete_file_dt(
                fd,
                comment=f"Removed {r.name} due to deletion policy ({row.days_to_keep} days)",
            )

            total_auto_deleted += 1

            if i % BATCH_SIZE == 0:
                frappe.db.commit()

    frappe.db.commit()

    # ------------------------------------------------
    # 8 File availability validation
    # ------------------------------------------------

    rows = frappe.db.sql(
        """
        SELECT name, attached_to_doctype, attached_to_name
        FROM `tabFile`
        WHERE file_available_on_server = 0
        AND is_folder = 0
        """,
        as_dict=True,
    )

    log.info(f"Checking availability of {len(rows)} files")

    avail_count = 0
    invalid_attachment = 0

    for i, r in enumerate(rows, 1):

        fd = frappe.get_doc("File", r.name)

        status = check_file_availability(fd)

        if status == 1:

            # Remove files attached to non-existent docs
            if r.attached_to_name and not frappe.db.exists(
                r.attached_to_doctype,
                r.attached_to_name,
            ):
                invalid_attachment += 1
                delete_file_dt(fd, ref_doc_exists=0)
                continue

            # Enforce privacy rules
            if fd.is_private != 1 and fd.attached_to_doctype:
                if fd.attached_to_doctype not in allowed_public:
                    fd.is_private = 1

            fd.file_available_on_server = 1
            fd.save()

        elif status == 2:

            check_and_move_file(fd)

        else:

            delete_file_dt(
                fd,
                comment="File removed since not available on server",
            )

        avail_count += 1

        if i % BATCH_SIZE == 0:
            frappe.db.commit()

    frappe.db.commit()

    runtime = int(time.time() - start)

    log.info(f"Files validated: {avail_count}")
    log.info(f"Invalid attachments removed: {invalid_attachment}")
    log.info(f"Auto deleted files: {total_auto_deleted}")
    log.info(f"Cleanup finished in {runtime}s")


def check_correct_folders():
    log = frappe.logger("file_cleanup")
    start = time.time()

    rebuild_tree(doctype="File", parent_field="folder", group_field="is_folder")
    frappe.db.commit()

    rebuild_time = time.time()

    folders = frappe.db.sql("""
        SELECT name, folder, file_size, important_document_for_archive
        FROM `tabFile`
        WHERE is_folder = 1
    """, as_dict=True)

    # fetch folder sizes in one query
    folder_sizes = frappe.db.sql("""
        SELECT folder, SUM(file_size) AS size
        FROM `tabFile`
        WHERE folder IS NOT NULL
        GROUP BY folder
    """, as_dict=True)

    size_map = {f.folder: f.size for f in folder_sizes}

    # fetch parent flags once
    parent_flags = frappe.db.sql("""
        SELECT name, important_document_for_archive
        FROM `tabFile`
        WHERE is_folder = 1
    """, as_dict=True)

    parent_map = {p.name: p.important_document_for_archive for p in parent_flags}

    for fd in folders:

        fd_size = size_map.get(fd.name, 0)

        # inherit archive flag
        if fd.folder:
            parent_flag = parent_map.get(fd.folder)

            if parent_flag == 1 and fd.important_document_for_archive != 1:
                frappe.db.set_value(
                    "File",
                    fd.name,
                    "important_document_for_archive",
                    1
                )

        if fd_size != fd.file_size:
            frappe.db.set_value(
                "File",
                fd.name,
                "file_size",
                fd_size
            )

            log.info(
                f"Updating Folder {fd.name} size {fd.file_size} → {fd_size}"
            )

    log.info(f"Tree rebuild time = {int(rebuild_time - start)}s")
    log.info(f"Total runtime = {int(time.time() - start)}s")

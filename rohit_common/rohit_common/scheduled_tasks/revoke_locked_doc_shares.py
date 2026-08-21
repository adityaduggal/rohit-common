# -*- coding: utf-8 -*-
# Copyright (c) 2026, Rohit Industries Group Private Limited and Contributors.
# For license information, please see license.txt

"""
Frappe's own permission engine ORs an explicit DocShare grant over whatever
has_permission()/permission_query_conditions return (see
frappe.permissions.has_permission -> false_if_not_shared(), and the
shared-condition OR in frappe.model.db_query.DatabaseQuery). That means a
document shared with a user before (or after) it crosses its retention
window in transaction_lock.py stays visible to that user regardless of the
lock - has_permission/permission_query_conditions never get a chance to
deny it. This daily job closes that gap by revoking DocShare grants on
locked documents held by users who aren't otherwise exempt (Administrator,
System Manager, or the configured bypass role).
"""

from __future__ import unicode_literals
import frappe

from rohit_common.rohit_common.validations.transaction_lock import (
    LOCKED_DOCTYPE_DATE_FIELDS,
    get_lock_row,
    has_bypass_role,
    is_admin_exempt,
    is_locked,
    parse_condition,
)


def execute():
    for doctype in LOCKED_DOCTYPE_DATE_FIELDS:
        revoke_shares_for_doctype(doctype)


def revoke_shares_for_doctype(doctype):
    row = get_lock_row(doctype)
    if not row or not row.days_to_keep:
        return

    date_field = LOCKED_DOCTYPE_DATE_FIELDS.get(doctype)
    if not date_field:
        return

    shares = frappe.get_all(
        "DocShare",
        filters={"share_doctype": doctype},
        fields=["name", "share_name", "user"],
    )
    if not shares:
        return

    exempt_users = {
        share.user for share in shares if is_admin_exempt(share.user) or has_bypass_role(share.user)
    }
    candidate_shares = [s for s in shares if s.user not in exempt_users]
    if not candidate_shares:
        return

    doc_fields = ["name", date_field]
    parsed_condition = parse_condition(row.doctype_conditions) if row.doctype_conditions else None
    if parsed_condition:
        doc_fields.append(parsed_condition[0])

    doc_names = list({s.share_name for s in candidate_shares})
    docs_by_name = {
        d["name"]: d
        for d in frappe.get_all(doctype, filters=[["name", "in", doc_names]], fields=doc_fields)
    }

    shares_to_revoke = []
    for share in candidate_shares:
        doc = docs_by_name.get(share.share_name)
        if not doc:
            continue
        doc["doctype"] = doctype
        if is_locked(doc):
            shares_to_revoke.append(share.name)

    if shares_to_revoke:
        frappe.db.delete("DocShare", {"name": ["in", shares_to_revoke]})
        frappe.db.commit()

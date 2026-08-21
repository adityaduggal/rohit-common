# -*- coding: utf-8 -*-
# Copyright (c) 2020, Rohit Industries Ltd. and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe.utils import flt
from frappe.model.document import Document


class RohitSettings(Document):
    def validate(self):
        if self.enable_einvoice == 1:
            if not self.einvoice_applicable_date:
                frappe.throw("E-Invoice Applicable Date is Mandatory")
            if self.eway_bill_limit < 1:
                frappe.throw(f"Enabling e-Invoice should enable Auto e-Way Bills for Invoices \
                    and Limit for the e-Way Bill should be greater than 1. Please correct the \
                    value {self.eway_bill_limit}")
        min_days_to_keep = 30
        self.sort_single_field_child("auto_deletion_policy_for_files", "document_type")
        self.sort_single_field_child("roles_allow_pub_att", "role")
        self.sort_single_field_child("docs_with_pub_att", "document_type")
        self.sort_single_field_child("auto_delete_from_version", "document_type")
        self.sort_single_field_child("bg_submit_cancel_docs", "document_type")
        self.sort_single_field_child("locked_doctypes", "document_type")
        for d in self.auto_deletion_policy_for_files:
            if flt(d.days_to_keep) < min_days_to_keep:
                frappe.throw(f"Minimum {min_days_to_keep} Days is Needed to Keep Files")
        self.validate_lock_conditions()

    def validate_lock_conditions(self):
        """
        Rows in locked_doctypes are read as a permission-check condition on every
        document open and list view (see transaction_lock.py) — unlike
        auto_deletion_policy_for_files' doctype_conditions (a scheduled job, lower
        stakes), a malformed or malicious condition here runs on a much hotter,
        more security-sensitive path, so it is restricted to a single
        field/operator/value comparison rather than accepted as free-form SQL.
        """
        from rohit_common.rohit_common.validations.transaction_lock import (
            parse_conditions,
        )

        for d in self.locked_doctypes:
            if not d.document_type:
                frappe.throw("Document Type is mandatory for each row in Locked Doctypes")
            if flt(d.days_to_keep) <= 0:
                frappe.throw(
                    f"Days to Keep must be greater than 0 for {d.document_type} in Locked Doctypes"
                )
            if d.doctype_conditions and not parse_conditions(d.doctype_conditions):
                frappe.throw(
                    f"Doctype Conditions for {d.document_type} must be one or more "
                    f"'field operator value' comparisons joined by AND (operators: = != > < is), "
                    f"e.g. \"outstanding_amount != 0 AND docstatus = 1\". Got: {d.doctype_conditions}"
                )

    def sort_single_field_child(self, table_name, field_name):
        sorted_table = []
        row_dict = {}
        idx = 1
        for row in self.get(table_name):
            print(row.__dict__)
            row_dict = row.__dict__
            del(row_dict["idx"])
            sorted_table.append(row_dict.copy())
        sorted_table = sorted(sorted_table, key=lambda i: i[field_name], reverse=0)
        self.set(table_name, [])
        for d in sorted_table:
            d["idx"] = idx
            idx += 1
            self.append(table_name, d)

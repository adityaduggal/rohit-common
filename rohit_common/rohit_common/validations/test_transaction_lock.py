# -*- coding: utf-8 -*-
# Copyright (c) 2026, Rohit Industries Group Private Limited and Contributors.
# For license information, please see license.txt
from __future__ import unicode_literals

import unittest

import frappe
from frappe.utils import add_days, nowdate

from rohit_common.rohit_common.validations.transaction_lock import (
    LOCKED_DOCTYPE_DATE_FIELDS,
    condition_holds,
    condition_sql,
    conditions_hold,
    conditions_sql,
    get_lock_row,
    has_bypass_role,
    has_permission,
    is_admin_exempt,
    is_locked,
    parse_condition,
    parse_conditions,
)

TEST_ROLE = "Test Transaction Lock Bypass Role"
TEST_USER = "test-transaction-lock@example.com"


class TestParseCondition(unittest.TestCase):
    """Pure grammar parsing — no DB needed."""

    def test_valid_conditions(self):
        self.assertEqual(parse_condition("outstanding_amount != 0"), ("outstanding_amount", "!=", "0"))
        self.assertEqual(parse_condition("status = 'Paid'"), ("status", "=", "'Paid'"))
        self.assertEqual(parse_condition("docstatus is None"), ("docstatus", "is", "None"))
        self.assertEqual(parse_condition("qty > 10"), ("qty", ">", "10"))

    def test_invalid_conditions_return_none(self):
        self.assertIsNone(parse_condition(""))
        self.assertIsNone(parse_condition(None))
        self.assertIsNone(parse_condition("outstanding_amount"))
        self.assertIsNone(parse_condition("1 == 1"))
        self.assertIsNone(parse_condition("outstanding_amount != 0 OR status = 'Draft'"))
        self.assertIsNone(parse_condition("DELETE FROM tabUser"))

    def test_is_only_accepts_null_values(self):
        # "is" only has a well-defined meaning as a null-check: MySQL's IS
        # operator rejects non-NULL/TRUE/FALSE/UNKNOWN values outright, so
        # anything else must be rejected at parse time.
        self.assertEqual(parse_condition("docstatus is None"), ("docstatus", "is", "None"))
        self.assertEqual(parse_condition("docstatus is null"), ("docstatus", "is", "null"))
        self.assertIsNone(parse_condition("status is 'Draft'"))
        self.assertIsNone(parse_condition("docstatus is 1"))


class TestParseConditions(unittest.TestCase):
    """AND-chained conditions — parse_conditions/conditions_hold/conditions_sql."""

    def test_single_clause_still_works(self):
        self.assertEqual(
            parse_conditions("outstanding_amount != 0"),
            [("outstanding_amount", "!=", "0")],
        )

    def test_two_clauses_joined_by_and(self):
        self.assertEqual(
            parse_conditions("outstanding_amount != 0 AND docstatus = 1"),
            [("outstanding_amount", "!=", "0"), ("docstatus", "=", "1")],
        )

    def test_and_is_case_insensitive(self):
        self.assertEqual(
            parse_conditions("outstanding_amount != 0 and docstatus = 1"),
            [("outstanding_amount", "!=", "0"), ("docstatus", "=", "1")],
        )

    def test_invalid_clause_fails_whole_chain(self):
        self.assertIsNone(parse_conditions("outstanding_amount != 0 AND docstatus"))
        self.assertIsNone(parse_conditions(""))
        self.assertIsNone(parse_conditions(None))

    def test_or_within_a_clause_still_rejected(self):
        self.assertIsNone(
            parse_conditions("outstanding_amount != 0 OR status = 'Draft'")
        )

    def test_conditions_hold_requires_all_clauses(self):
        parsed = parse_conditions("outstanding_amount != 0 AND docstatus = 1")
        doc = frappe._dict({"outstanding_amount": 500, "docstatus": 1})
        self.assertTrue(conditions_hold(doc, parsed))
        doc = frappe._dict({"outstanding_amount": 0, "docstatus": 1})
        self.assertFalse(conditions_hold(doc, parsed))
        doc = frappe._dict({"outstanding_amount": 500, "docstatus": 0})
        self.assertFalse(conditions_hold(doc, parsed))

    def test_conditions_sql_ands_fragments(self):
        parsed = parse_conditions("outstanding_amount != 0 AND docstatus = 1")
        sql = conditions_sql("Sales Invoice", parsed)
        self.assertEqual(
            sql,
            "`tabSales Invoice`.`outstanding_amount` != '0' AND `tabSales Invoice`.`docstatus` = '1'",
        )


class TestConditionHolds(unittest.TestCase):
    def test_numeric_not_equal(self):
        doc = frappe._dict({"outstanding_amount": 500})
        self.assertTrue(condition_holds(doc, "outstanding_amount", "!=", "0"))
        doc = frappe._dict({"outstanding_amount": 0})
        self.assertFalse(condition_holds(doc, "outstanding_amount", "!=", "0"))

    def test_string_equal(self):
        doc = frappe._dict({"status": "Paid"})
        self.assertTrue(condition_holds(doc, "status", "=", "'Paid'"))
        self.assertFalse(condition_holds(doc, "status", "=", "'Unpaid'"))

    def test_is_none(self):
        doc = frappe._dict({"docstatus": None})
        self.assertTrue(condition_holds(doc, "docstatus", "is", "None"))
        doc = frappe._dict({"docstatus": 1})
        self.assertFalse(condition_holds(doc, "docstatus", "is", "None"))

    def test_greater_less_than(self):
        doc = frappe._dict({"qty": 15})
        self.assertTrue(condition_holds(doc, "qty", ">", "10"))
        self.assertFalse(condition_holds(doc, "qty", "<", "10"))


class TestConditionSql(unittest.TestCase):
    def test_numeric_fragment(self):
        # frappe.db.escape() quotes every value regardless of type (even
        # ints) - MySQL coerces '0' to 0 against a numeric column, so this
        # is correct even though it isn't bare-numeric SQL.
        sql = condition_sql("Sales Invoice", "outstanding_amount", "!=", "0")
        self.assertEqual(sql, "`tabSales Invoice`.`outstanding_amount` != '0'")

    def test_string_fragment_is_escaped(self):
        sql = condition_sql("Sales Invoice", "status", "=", "'Draft'")
        self.assertIn("`tabSales Invoice`.`status` =", sql)
        self.assertIn("Draft", sql)

    def test_is_null(self):
        sql = condition_sql("Sales Invoice", "docstatus", "is", "None")
        self.assertEqual(sql, "`tabSales Invoice`.`docstatus` IS NULL")


class TestTransactionLockIntegration(unittest.TestCase):
    """
    DB-backed tests for is_locked()/has_permission() against Rohit Settings.
    Mirrors the setUp/tearDown-with-rollback pattern used elsewhere in this
    app's test suite (see test_rohit_common_utils.py).
    """

    @classmethod
    def setUpClass(cls):
        if not frappe.db.exists("Role", TEST_ROLE):
            frappe.get_doc({"doctype": "Role", "role_name": TEST_ROLE}).insert(
                ignore_permissions=True
            )
        if not frappe.db.exists("User", TEST_USER):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": TEST_USER,
                    "first_name": "Transaction Lock Test",
                    "send_welcome_email": 0,
                    "roles": [{"role": TEST_ROLE}],
                }
            ).insert(ignore_permissions=True)

    def setUp(self):
        self.settings = frappe.get_single("Rohit Settings")
        self._original_locked_doctypes = [d.as_dict() for d in self.settings.locked_doctypes]
        self._original_bypass_role = self.settings.transaction_lock_bypass_role
        self.settings.set("locked_doctypes", [])
        self.settings.transaction_lock_bypass_role = TEST_ROLE
        self.settings.append(
            "locked_doctypes",
            {
                "document_type": "Sales Invoice",
                "days_to_keep": 30,
                "doctype_conditions": "outstanding_amount != 0",
            },
        )
        self.settings.save(ignore_permissions=True)
        frappe.clear_cache(doctype="Rohit Settings")

    def tearDown(self):
        self.settings = frappe.get_single("Rohit Settings")
        self.settings.set("locked_doctypes", self._original_locked_doctypes)
        self.settings.transaction_lock_bypass_role = self._original_bypass_role
        self.settings.save(ignore_permissions=True)
        frappe.clear_cache(doctype="Rohit Settings")

    def test_get_lock_row_matches_configured_doctype(self):
        row = get_lock_row("Sales Invoice")
        self.assertIsNotNone(row)
        self.assertEqual(row.days_to_keep, 30)

    def test_get_lock_row_none_for_unconfigured_doctype(self):
        self.assertIsNone(get_lock_row("Purchase Order"))

    def test_is_locked_true_when_old_and_paid(self):
        doc = frappe._dict(
            {
                "doctype": "Sales Invoice",
                "posting_date": add_days(nowdate(), -60),
                "outstanding_amount": 0,
            }
        )
        self.assertTrue(is_locked(doc))

    def test_is_locked_false_within_retention_window(self):
        doc = frappe._dict(
            {
                "doctype": "Sales Invoice",
                "posting_date": add_days(nowdate(), -5),
                "outstanding_amount": 0,
            }
        )
        self.assertFalse(is_locked(doc))

    def test_is_locked_false_when_unpaid_exception_holds(self):
        doc = frappe._dict(
            {
                "doctype": "Sales Invoice",
                "posting_date": add_days(nowdate(), -60),
                "outstanding_amount": 500,
            }
        )
        self.assertFalse(is_locked(doc))

    def test_is_locked_false_for_doctype_with_no_lock_row(self):
        doc = frappe._dict(
            {
                "doctype": "Purchase Order",
                "transaction_date": add_days(nowdate(), -9999),
            }
        )
        self.assertFalse(is_locked(doc))

    def test_has_bypass_role_true_for_configured_role(self):
        self.assertTrue(has_bypass_role(TEST_USER))

    def test_has_bypass_role_false_without_role(self):
        self.assertFalse(has_bypass_role("Guest"))

    def test_is_admin_exempt(self):
        self.assertTrue(is_admin_exempt("Administrator"))
        self.assertFalse(is_admin_exempt(TEST_USER))

    def test_has_permission_none_for_admin(self):
        doc = frappe._dict(
            {
                "doctype": "Sales Invoice",
                "name": "TEST-SINV-LOCK-1",
                "posting_date": add_days(nowdate(), -60),
                "outstanding_amount": 0,
            }
        )
        self.assertIsNone(has_permission(doc, ptype="read", user="Administrator"))

    def test_has_permission_false_when_locked_and_no_bypass(self):
        doc = frappe._dict(
            {
                "doctype": "Sales Invoice",
                "name": "TEST-SINV-LOCK-2",
                "posting_date": add_days(nowdate(), -60),
                "outstanding_amount": 0,
            }
        )
        self.assertFalse(has_permission(doc, ptype="read", user="Guest"))

    def test_has_permission_none_when_not_locked(self):
        doc = frappe._dict(
            {
                "doctype": "Sales Invoice",
                "name": "TEST-SINV-LOCK-3",
                "posting_date": add_days(nowdate(), -5),
                "outstanding_amount": 0,
            }
        )
        self.assertIsNone(has_permission(doc, ptype="read", user="Guest"))

    def test_has_permission_logs_bypass_access(self):
        # Transaction Lock Access Log.reference_name is a Dynamic Link, which
        # validates that the referenced document actually exists - use a
        # real Sales Invoice rather than a synthetic name.
        real_invoice_name = frappe.db.get_value("Sales Invoice", {}, "name")
        if not real_invoice_name:
            self.skipTest("No Sales Invoice exists on this site to reference")

        frappe.db.delete(
            "Transaction Lock Access Log",
            {"reference_doctype": "Sales Invoice", "reference_name": real_invoice_name},
        )
        doc = frappe._dict(
            {
                "doctype": "Sales Invoice",
                "name": real_invoice_name,
                "posting_date": add_days(nowdate(), -60),
                "outstanding_amount": 0,
            }
        )
        result = has_permission(doc, ptype="read", user=TEST_USER)
        self.assertIsNone(result)
        self.assertTrue(
            frappe.db.exists(
                "Transaction Lock Access Log",
                {
                    "user": TEST_USER,
                    "reference_doctype": "Sales Invoice",
                    "reference_name": real_invoice_name,
                },
            )
        )
        frappe.db.delete(
            "Transaction Lock Access Log",
            {"reference_doctype": "Sales Invoice", "reference_name": real_invoice_name},
        )

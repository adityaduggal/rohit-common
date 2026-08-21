# -*- coding: utf-8 -*-
# Copyright (c) 2026, Rohit Industries Group Private Limited and Contributors.
# For license information, please see license.txt
from __future__ import unicode_literals

import unittest

import frappe

from rohit_common.utils.query_guard import assert_max_queries
from rohit_common.rohit_common.report.stock_ledger_normal.stock_ledger_normal import (
    execute,
    get_stock_entry_link,
)


class TestStockLedgerNormal(unittest.TestCase):
    """Read-only against whatever Stock Ledger Entry data already exists on
    the test site - this report has no filters that require pre-built
    fixtures, and the point of these tests is to pin down query behaviour
    against a realistically large, mixed-voucher-type result set."""

    def test_query_count_is_bounded_not_per_row(self):
        """Regression guard for the N+1 fix: the old implementation called
        frappe.get_doc() once per row to resolve the Linked Name/Link Type
        columns, so query count scaled linearly with row count. The batched
        implementation issues at most one query per voucher type present in
        the result set, so the ceiling here is a small constant regardless
        of how many rows match."""
        filters = get_filters_with_enough_rows(min_rows=50)
        if filters is None:
            self.skipTest("Not enough Stock Ledger Entry data on this site to exercise the report")

        with assert_max_queries(12, test_case=self) as guard:
            columns, data = execute(filters)

        self.assertGreaterEqual(len(data), 50)
        # Sanity: query count must not have scaled anywhere near row count.
        self.assertLess(guard.count, len(data))

    def test_linked_name_matches_source_document(self):
        filters = get_filters_with_enough_rows(min_rows=50)
        if filters is None:
            self.skipTest("Not enough Stock Ledger Entry data on this site to exercise the report")

        columns, data = execute(filters)
        voucher_no_idx, voucher_type_idx, linked_name_idx = 7, 8, 9

        checked_types = set()
        party_field_by_type = {
            "Delivery Note": "customer",
            "Sales Invoice": "customer",
            "Purchase Receipt": "supplier",
            "Purchase Invoice": "supplier",
        }
        for row in data:
            voucher_type = row[voucher_type_idx]
            fieldname = party_field_by_type.get(voucher_type)
            if not fieldname or voucher_type in checked_types:
                continue
            expected = frappe.db.get_value(voucher_type, row[voucher_no_idx], fieldname)
            self.assertEqual(row[linked_name_idx], expected)
            checked_types.add(voucher_type)
            if checked_types == set(party_field_by_type):
                break

    def test_get_stock_entry_link_follows_priority_order(self):
        self.assertEqual(
            get_stock_entry_link(frappe._dict(process_job_card="JC-1", sales_order="SO-1")),
            ("Process Job Card RIGPL", "JC-1"),
        )
        self.assertEqual(
            get_stock_entry_link(frappe._dict(process_job_card=None, sales_order="SO-1")),
            ("Sales Order", "SO-1"),
        )
        self.assertEqual(
            get_stock_entry_link(frappe._dict(process_job_card=None, sales_order=None)),
            (None, None),
        )


def get_filters_with_enough_rows(min_rows):
    """Find the narrowest recent posting-date range on this site with at
    least `min_rows` non-cancelled Stock Ledger Entries, so the query-count
    guard exercises a real, sizeable, mixed-voucher-type dataset instead of
    an empty report."""
    counts_by_date = frappe.db.sql(
        """SELECT posting_date, COUNT(*) FROM `tabStock Ledger Entry`
        WHERE is_cancelled = 'No' GROUP BY posting_date ORDER BY posting_date DESC"""
    )
    if not counts_by_date:
        return None

    to_date = counts_by_date[0][0]
    running_total = 0
    for posting_date, day_count in counts_by_date:
        running_total += day_count
        from_date = posting_date
        if running_total >= min_rows:
            break
    else:
        return None

    return {"from_date": from_date, "to_date": to_date}

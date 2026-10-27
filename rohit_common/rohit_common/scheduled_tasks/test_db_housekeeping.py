# -*- coding: utf-8 -*-
# Copyright (c) 2026, Rohit Industries Group Private Limited and Contributors.
# For license information, please see license.txt
"""
Run: bench --site dev-rb-v12 run-tests --module rohit_common.rohit_common.scheduled_tasks.test_db_housekeeping
"""
from __future__ import unicode_literals

import unittest
from unittest.mock import patch

import frappe

from rohit_common.rohit_common.scheduled_tasks import db_housekeeping
from rohit_common.utils.query_guard import assert_max_queries

TEST_PREFIX = "test-dbhk-"
TEST_ITEM = "_Test DBHK Item"
TEST_WAREHOUSE = "_Test DBHK Warehouse"
# Real SLEs start in 2011, so a cutoff in 1720 never trims a real SLE.
TEST_CUTOFF = "1720-01-03"
FULL_QUEUE = "[[1.0, 10.0]]"
TEST_CREATION = "1726-01-01 00:00:00"
# The test rows are about 109,600 days old. Real rows are all younger than DELETE_DAYS.
DELETE_DAYS = 100000


class TestTrimStockQueue(unittest.TestCase):
	"""trim_stock_queue() commits after each batch, so this suite cleans up by name."""

	def setUp(self):
		self._delete_test_sles()
		self._sle("old-1", "1720-01-01")
		self._sle("old-2", "1720-01-02")
		self._sle("keeper", "1720-01-03", creation="1720-01-03 10:00:00")
		# Later creation than the keeper, but cancelled, so it must not be the keeper
		self._sle("cancelled", "1720-01-03", creation="1720-01-03 11:00:00", is_cancelled=1)
		self._sle("after-cutoff", "1720-01-04")
		frappe.db.commit()

	def tearDown(self):
		self._delete_test_sles()
		frappe.db.commit()

	def test_keeps_last_queue_before_cutoff_and_all_after(self):
		trimmed = db_housekeeping.trim_stock_queue(TEST_CUTOFF)
		self.assertEqual(trimmed, 3)
		self.assertEqual(self._queues(), {
			"after-cutoff": FULL_QUEUE,
			"cancelled": "[]",
			"keeper": FULL_QUEUE,
			"old-1": "[]",
			"old-2": "[]",
		})

	def test_second_run_trims_nothing(self):
		db_housekeeping.trim_stock_queue(TEST_CUTOFF)
		self.assertEqual(db_housekeeping.trim_stock_queue(TEST_CUTOFF), 0)

	def test_queries_scale_with_item_warehouse_pairs_not_rows(self):
		pairs = len(frappe.db.sql("""SELECT DISTINCT item_code, warehouse
			FROM `tabStock Ledger Entry`"""))
		# 1 for the pairs, 1 keeper lookup per pair, and 1 UPDATE + 1 COMMIT for the test pair
		with assert_max_queries(1 + pairs + 2, test_case=self):
			db_housekeeping.trim_stock_queue(TEST_CUTOFF)

	def _sle(self, suffix, posting_date, creation=None, is_cancelled=0):
		frappe.db.sql("""INSERT INTO `tabStock Ledger Entry` (name, item_code, warehouse,
			posting_date, posting_time, creation, modified, is_cancelled, stock_queue)
			VALUES (%(name)s, %(item)s, %(wh)s, %(date)s, '10:00:00', %(creation)s, %(creation)s,
			%(is_cancelled)s, %(queue)s)""", {
			"name": TEST_PREFIX + suffix, "item": TEST_ITEM, "wh": TEST_WAREHOUSE,
			"date": posting_date, "creation": creation or posting_date + " 10:00:00",
			"is_cancelled": is_cancelled, "queue": FULL_QUEUE})

	def _queues(self):
		rows = frappe.db.sql("""SELECT name, stock_queue FROM `tabStock Ledger Entry`
			WHERE item_code = %s""", TEST_ITEM)
		return {name[len(TEST_PREFIX):]: queue for name, queue in rows}

	def _delete_test_sles(self):
		frappe.db.sql("DELETE FROM `tabStock Ledger Entry` WHERE item_code = %s", TEST_ITEM)


class TestFreezeStockUpto(unittest.TestCase):
	def setUp(self):
		self.original = frappe.db.get_single_value("Stock Settings", "stock_frozen_upto")

	def tearDown(self):
		frappe.db.set_value("Stock Settings", None, "stock_frozen_upto", self.original)
		frappe.db.commit()

	def test_moves_forward(self):
		frappe.db.set_value("Stock Settings", None, "stock_frozen_upto", "2015-07-31")
		db_housekeeping.freeze_stock_upto("2025-03-31")
		self.assertEqual(str(self._frozen_upto()), "2025-03-31")

	def test_never_moves_back(self):
		frappe.db.set_value("Stock Settings", None, "stock_frozen_upto", "2025-03-31")
		db_housekeeping.freeze_stock_upto("2015-07-31")
		self.assertEqual(str(self._frozen_upto()), "2025-03-31")

	def _frozen_upto(self):
		return frappe.db.get_single_value("Stock Settings", "stock_frozen_upto")


class TestExecute(unittest.TestCase):
	def test_no_period_closing_skips_trim_and_freeze(self):
		with patch.object(db_housekeeping, "get_stock_queue_cutoff", return_value=None), \
				patch.object(db_housekeeping, "trim_stock_queue") as trim, \
				patch.object(db_housekeeping, "freeze_stock_upto") as freeze, \
				patch.object(db_housekeeping, "delete_noise_versions", return_value=0), \
				patch.object(db_housekeeping, "purge_access_log", return_value=0), \
				patch.object(db_housekeeping, "delete_orphan_global_search", return_value=0), \
				patch.object(db_housekeeping, "drop_orphan_tables"):
			db_housekeeping.execute()
		trim.assert_not_called()
		freeze.assert_not_called()


class TestLogCleanup(unittest.TestCase):
	"""The clean-ups commit after each batch, so this suite cleans up by name."""

	def setUp(self):
		self._delete_test_rows()
		self._version("Route History", "noise")
		self._version("Note", "business")
		self._access_log("old", TEST_CREATION)
		self._access_log("recent", "1900-01-01 00:00:00")
		frappe.db.commit()

	def tearDown(self):
		self._delete_test_rows()
		frappe.db.commit()

	def test_deletes_only_noise_doctype_versions(self):
		with patch.object(db_housekeeping, "NOISE_VERSION_DAYS", DELETE_DAYS):
			db_housekeeping.delete_noise_versions()
		remaining = frappe.get_all("Version", filters={"docname": ["like", TEST_PREFIX + "%"]},
			pluck="ref_doctype")
		self.assertEqual(remaining, ["Note"])

	def test_purges_only_access_logs_older_than_days(self):
		self.assertEqual(db_housekeeping.purge_access_log(DELETE_DAYS), 1)
		remaining = frappe.get_all("Access Log", filters={"name": ["like", TEST_PREFIX + "%"]},
			pluck="name")
		self.assertEqual(remaining, [TEST_PREFIX + "recent"])

	def _version(self, ref_doctype, suffix):
		version = frappe.get_doc({
			"doctype": "Version",
			"ref_doctype": ref_doctype,
			"docname": TEST_PREFIX + suffix,
			"data": "{}",
		}).insert(ignore_permissions=True)
		frappe.db.sql("UPDATE `tabVersion` SET creation = %s WHERE name = %s",
			(TEST_CREATION, version.name))

	def _access_log(self, suffix, creation):
		frappe.db.sql("""INSERT INTO `tabAccess Log` (name, creation, modified)
			VALUES (%s, %s, %s)""", (TEST_PREFIX + suffix, creation, creation))

	def _delete_test_rows(self):
		frappe.db.delete("Version", {"docname": ["like", TEST_PREFIX + "%"]})
		frappe.db.sql("DELETE FROM `tabAccess Log` WHERE name LIKE %s", TEST_PREFIX + "%")

# -*- coding: utf-8 -*-
# Copyright (c) 2026, Rohit Industries Group Private Limited and Contributors.
# For license information, please see license.txt
"""
Run: bench --site dev-rb-v12 run-tests --module rohit_common.rohit_common.scheduled_tasks.test_auto_delete_version
"""
from __future__ import unicode_literals

import unittest
from unittest.mock import patch

import frappe

from rohit_common.rohit_common.scheduled_tasks import auto_delete_version
from rohit_common.rohit_common.scheduled_tasks.auto_delete_version import delete_old_versions

TEST_DOCNAME_PREFIX = "test-22-version-"
TEST_CREATION = "1726-01-01 00:00:00"
# The test rows are about 109,600 days old. Only rows older than 1753 match DELETE_DAYS, and
# no row matches KEEP_DAYS, so the real Versions on the site are never deleted.
DELETE_DAYS = 100000
KEEP_DAYS = 200000


class TestAutoDeleteVersion(unittest.TestCase):
	"""delete_old_versions() commits after each batch, so this suite cleans up by docname."""

	def setUp(self):
		self._delete_test_versions()
		for doctype in ("ToDo", "Note", "Event"):
			self._old_version(doctype)
		frappe.db.commit()

	def tearDown(self):
		self._delete_test_versions()
		frappe.db.commit()

	def _delete_test_versions(self):
		frappe.db.delete("Version", {"docname": ["like", TEST_DOCNAME_PREFIX + "%"]})

	def _old_version(self, doctype, suffix=""):
		version = frappe.get_doc({
			"doctype": "Version",
			"ref_doctype": doctype,
			"docname": TEST_DOCNAME_PREFIX + doctype + suffix,
			"data": "{}",
		}).insert(ignore_permissions=True)
		frappe.db.sql("UPDATE `tabVersion` SET creation = %s WHERE name = %s", (TEST_CREATION, version.name))

	def _remaining(self):
		return sorted(frappe.get_all("Version", filters={"docname": ["like", TEST_DOCNAME_PREFIX + "%"]},
			pluck="ref_doctype"))

	def test_no_listed_doctypes_deletes_all_old_versions(self):
		# Before #22 an empty list made `NOT IN ()`, a SQL syntax error
		delete_old_versions(DELETE_DAYS, {})
		self.assertEqual(self._remaining(), [])

	def test_one_listed_doctype_keeps_its_versions_for_its_own_days(self):
		# Before #22 one doctype made `NOT IN ('ToDo',)`, a SQL syntax error
		delete_old_versions(DELETE_DAYS, {"ToDo": KEEP_DAYS})
		self.assertEqual(self._remaining(), ["ToDo"])

	def test_two_listed_doctypes_use_their_own_days_not_the_global_days(self):
		delete_old_versions(KEEP_DAYS, {"ToDo": KEEP_DAYS, "Note": DELETE_DAYS})
		self.assertEqual(self._remaining(), ["Event", "ToDo"])

	def test_deletes_in_batches_until_none_left(self):
		self._old_version("Note", suffix="-2")
		self._old_version("Note", suffix="-3")
		frappe.db.commit()
		with patch.object(auto_delete_version, "VERSION_DELETE_BATCH", 2):
			deleted = delete_old_versions(KEEP_DAYS, {"Note": DELETE_DAYS})
		self.assertEqual(deleted, 3)
		self.assertEqual(self._remaining(), ["Event", "ToDo"])

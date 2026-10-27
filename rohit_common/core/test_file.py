# -*- coding: utf-8 -*-
# Copyright (c) 2026, Rohit Industries Group Private Limited and Contributors.
# For license information, please see license.txt
from __future__ import unicode_literals

import os
import unittest

import frappe
from frappe.utils import get_files_path

from rohit_common.core.file import (
	check_other_files_with_same_file,
	custom_file_permissions,
	get_other_files_by_name,
)
from rohit_common.utils.query_guard import assert_max_queries
from rohit_common.utils.rohit_common_utils import check_system_manager

TEST_USER = "test-file-perm@example.com"
QUOTE_FILE_NAME = "test-o'brien-file.txt"


class TestFileHooks(unittest.TestCase):
	"""Issue #21: File permission hook and File SQL."""

	@classmethod
	def setUpClass(cls):
		if not frappe.db.exists("User", TEST_USER):
			frappe.get_doc({
				"doctype": "User",
				"email": TEST_USER,
				"first_name": "File Perm Test",
				"send_welcome_email": 0,
			}).insert(ignore_permissions=True)
		frappe.db.commit()

	def setUp(self):
		self._hard_delete()

	def tearDown(self):
		self._hard_delete()
		frappe.db.commit()

	def _hard_delete(self):
		frappe.db.delete("File", {"file_name": QUOTE_FILE_NAME})
		path = get_files_path(QUOTE_FILE_NAME, is_private=1)
		if os.path.exists(path):
			os.remove(path)

	def _private_file(self, **kwargs):
		doc = frappe.get_doc(dict({
			"doctype": "File",
			"file_name": QUOTE_FILE_NAME,
			"is_private": 1,
			"content": "test content",
		}, **kwargs)).insert(ignore_permissions=True)
		frappe.db.commit()
		return doc

	def test_file_name_with_quote_saves(self):
		doc = self._private_file()
		doc.save(ignore_permissions=True)
		self.assertEqual(get_other_files_by_name(doc), [])
		self.assertEqual(check_other_files_with_same_file(doc), 0)

	def test_check_system_manager_with_quote_in_user(self):
		self.assertEqual(check_system_manager("a'b@example.com"), 0)
		self.assertEqual(check_system_manager("Administrator"), 1)

	def test_public_file_permission_needs_no_share_lookup(self):
		doc = frappe._dict({"doctype": "File", "name": "x", "is_private": 0, "owner": "Administrator"})
		custom_file_permissions(doc, "read", TEST_USER)
		with assert_max_queries(0, test_case=self):
			self.assertTrue(custom_file_permissions(doc, "read", TEST_USER))

	def test_private_file_permission_query_count(self):
		doc = self._private_file()
		custom_file_permissions(doc, "read", TEST_USER)
		# The DocShare lookup only
		with assert_max_queries(1, test_case=self):
			self.assertFalse(custom_file_permissions(doc, "read", TEST_USER))

	def test_attached_file_checks_the_passed_user(self):
		todo = frappe.get_doc({"doctype": "ToDo", "description": "test file perm"}).insert(
			ignore_permissions=True)
		doc = self._private_file(attached_to_doctype="ToDo", attached_to_name=todo.name)
		# The session user is Administrator, but the test user cannot read the ToDo
		self.assertFalse(custom_file_permissions(doc, "read", TEST_USER))
		self.assertTrue(custom_file_permissions(doc, "read", "Administrator"))
		frappe.delete_doc("ToDo", todo.name, force=1, ignore_permissions=True)

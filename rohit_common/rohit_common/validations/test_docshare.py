# -*- coding: utf-8 -*-
# Copyright (c) 2026, Rohit Industries Group Private Limited and Contributors.
# For license information, please see license.txt
from __future__ import unicode_literals

import unittest

import frappe
import frappe.share

TEST_USERS = ["test-docshare-a@example.com", "test-docshare-b@example.com"]
TEST_FOLDER_NAMES = ["test-ds-top", "test-ds-mid", "test-ds-low"]


class TestFolderShare(unittest.TestCase):
	"""
	Issue #21: sharing a folder shares its whole subtree once, with no
	NameError and no recursive walk; unsharing removes only that user's
	child shares.
	"""

	@classmethod
	def setUpClass(cls):
		for email in TEST_USERS:
			if not frappe.db.exists("User", email):
				frappe.get_doc({
					"doctype": "User",
					"email": email,
					"first_name": "DocShare Test",
					"send_welcome_email": 0,
				}).insert(ignore_permissions=True)
		frappe.db.commit()

	def setUp(self):
		self._hard_delete()
		self.top = self._folder("test-ds-top", None)
		self.mid = self._folder("test-ds-mid", self.top.name)
		self.low = self._folder("test-ds-low", self.mid.name)
		frappe.db.commit()
		self.children = [self.mid.name, self.low.name]

	def tearDown(self):
		self._hard_delete()
		frappe.db.commit()

	def _hard_delete(self):
		names = frappe.get_all("File", filters={"file_name": ["in", TEST_FOLDER_NAMES]}, pluck="name")
		if names:
			frappe.db.delete("DocShare", {"share_doctype": "File", "share_name": ["in", names]})
		frappe.db.delete("File", {"file_name": ["in", TEST_FOLDER_NAMES]})

	def _folder(self, file_name, folder):
		return frappe.get_doc({
			"doctype": "File",
			"file_name": file_name,
			"is_folder": 1,
			"folder": folder,
			"is_private": 1,
		}).insert(ignore_permissions=True)

	def _child_shares(self, user):
		return frappe.get_all("DocShare", filters={"user": user, "share_doctype": "File",
			"share_name": ["in", self.children]}, fields=["share_name", "write"])

	def test_share_folder_makes_one_share_per_child(self):
		frappe.share.add("File", self.top.name, TEST_USERS[0], read=1)
		shares = self._child_shares(TEST_USERS[0])
		self.assertEqual(sorted(s.share_name for s in shares), sorted(self.children))

	def test_changed_share_updates_children(self):
		frappe.share.add("File", self.top.name, TEST_USERS[0], read=1)
		frappe.share.add("File", self.top.name, TEST_USERS[0], read=1, write=1)
		shares = self._child_shares(TEST_USERS[0])
		self.assertEqual(len(shares), len(self.children))
		self.assertTrue(all(s.write == 1 for s in shares))

	def test_unshare_removes_only_that_users_children(self):
		frappe.share.add("File", self.top.name, TEST_USERS[0], read=1)
		frappe.share.add("File", self.top.name, TEST_USERS[1], read=1)
		frappe.share.remove("File", self.top.name, TEST_USERS[0])
		self.assertEqual(self._child_shares(TEST_USERS[0]), [])
		self.assertEqual(len(self._child_shares(TEST_USERS[1])), len(self.children))

	def test_share_to_administrator_skips_children(self):
		frappe.share.add("File", self.top.name, "Administrator", read=1)
		self.assertEqual(self._child_shares("Administrator"), [])

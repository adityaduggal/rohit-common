# -*- coding: utf-8 -*-
# Copyright (c) 2026, Rohit Industries Group Private Limited and Contributors.
# For license information, please see license.txt
from __future__ import unicode_literals

import unittest

import frappe

from rohit_common.utils.query_guard import assert_max_queries
from rohit_common.rohit_common.scheduled_tasks.delete_unneeded_files import check_correct_folders

TEST_FILE_NAMES = ["test-n1-root", "test-n1-child"]


class TestDeleteUnneededFiles(unittest.TestCase):
	"""
	NOTE: File has its own on_rollback() hook (check_folder_is_empty()), so
	wrapping File creation/deletion in frappe.db.rollback() for test isolation
	doesn't cleanly undo itself and can leave rows behind after a failed run.
	This suite hard-deletes by name (bypassing document hooks) instead, both
	up front (in case a previous run left rows behind) and in tearDown.
	"""

	def setUp(self):
		self._hard_delete_test_files()
		self.root = frappe.get_doc({
			"doctype": "File",
			"file_name": "test-n1-root",
			"is_folder": 1,
			"is_private": 1,
		}).insert(ignore_permissions=True)
		self.child = frappe.get_doc({
			"doctype": "File",
			"file_name": "test-n1-child",
			"is_folder": 1,
			"folder": self.root.name,
			"is_private": 1,
		}).insert(ignore_permissions=True)
		frappe.db.commit()

	def tearDown(self):
		self._hard_delete_test_files()
		frappe.db.commit()

	def _hard_delete_test_files(self):
		# Low-level delete: skips File.on_trash()/check_folder_is_empty(), which
		# would otherwise refuse to delete a folder that still has children -
		# an ordering problem this suite doesn't need to solve for cleanup.
		frappe.db.delete("File", {"file_name": ["in", TEST_FILE_NAMES]})

	def test_check_correct_folders_query_count_scales_sublinearly(self):
		"""Regression guard: check_correct_folders() must not issue one query per
		row. It legitimately issues one batched UPDATE per 500-row chunk (a real
		site can have tens of thousands of File rows, and a single SQL statement
		can't be unbounded), so the ceiling here scales with actual table size
		instead of a fixed constant - what this guards against is a per-*row*
		query count creeping back in, not a fixed absolute number."""
		chunk_size = 500
		total_files = frappe.db.count("File")
		expected_chunks = (total_files // chunk_size) + 1
		# A handful of fixed-shape queries (rebuild_tree's read, commit, the two
		# check_correct_folders reads) plus up to ~3 batched-UPDATE chunks worth
		# of margin (lft/rgt writes scale with total_files; archive/size writes
		# scale with folder count, which is <= total_files).
		expected_ceiling = 6 + expected_chunks * 3
		with assert_max_queries(expected_ceiling, test_case=self):
			check_correct_folders()

	def test_check_correct_folders_propagates_archive_flag_from_parent(self):
		self.root.important_document_for_archive = 1
		self.root.save(ignore_permissions=True)
		frappe.db.commit()

		check_correct_folders()

		self.assertEqual(
			frappe.db.get_value("File", self.child.name, "important_document_for_archive"), 1
		)

	def test_check_correct_folders_handles_root_folder_with_no_parent(self):
		"""Regression test for the pre-existing bug where a root folder (no
		`folder` set) could reference a stale/undefined file-size total from a
		previous loop iteration."""
		# Should not raise, and should compute a real size for the root folder too.
		check_correct_folders()
		size = frappe.db.get_value("File", self.root.name, "file_size")
		self.assertIsNotNone(size)

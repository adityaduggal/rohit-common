# -*- coding: utf-8 -*-
# Copyright (c) 2026, Rohit Industries Group Private Limited and Contributors.
# For license information, please see license.txt
from __future__ import unicode_literals

import os
import unittest

import frappe
from frappe.utils import get_files_path

from rohit_common.utils.query_guard import assert_max_queries
from rohit_common.utils.rohit_common_utils import rebuild_tree


TEST_FILE_NAMES = [
	"test-n1-tree-root-a", "test-n1-tree-root-b", "test-n1-tree-child-a",
	"test-n1-tree-leaf-a", "test-n1-tree-leaf-b",
]
TEST_LEAF_FILE_NAMES = ["test-n1-tree-leaf-a", "test-n1-tree-leaf-b"]


class TestRebuildTree(unittest.TestCase):
	"""
	rebuild_tree() was rewritten from a per-row recursive-query implementation
	to a single-fetch, in-memory, batched-write implementation. These tests
	check nested-set correctness (the thing most likely to break in that
	rewrite), not just query count.

	NOTE: File has its own on_rollback() hook (check_folder_is_empty()), so
	wrapping File creation/deletion in frappe.db.rollback() for test isolation
	doesn't cleanly undo itself and can leave rows behind after a failed run.
	This suite hard-deletes by name (bypassing document hooks) instead.

	Also NOTE: rebuild_tree()/check_correct_folders() operate on the entire
	File table by design (not scoped to a subtree) - this is inherent to the
	function as called in production (delete_unneeded_files.check_correct_folders),
	not something this test introduces. Running it recomputes lft/rgt for
	every File row on the site, which is expected but can be slow on a large
	table.
	"""

	def setUp(self):
		self._hard_delete_test_files()
		# Two independent root-level groups, each with one child group and one
		# leaf file, plus a leaf directly under root. This shape specifically
		# exercises the multi-root-group case that had the lft/rgt-overlap bug.
		self.root_a = self._folder("test-n1-tree-root-a", is_folder=1)
		self.root_b = self._folder("test-n1-tree-root-b", is_folder=1)
		self.child_a = self._folder("test-n1-tree-child-a", is_folder=1, folder=self.root_a.name)
		self.leaf_a = self._folder("test-n1-tree-leaf-a", is_folder=0, folder=self.child_a.name)
		self.leaf_b = self._folder("test-n1-tree-leaf-b", is_folder=0, folder=self.root_b.name)
		frappe.db.commit()

	def tearDown(self):
		self._hard_delete_test_files()
		frappe.db.commit()

	def _hard_delete_test_files(self):
		frappe.db.delete("File", {"file_name": ["in", TEST_FILE_NAMES]})
		# frappe.db.delete() bypasses File's own hooks, so it never removes the
		# physical file that `content=` (in _folder()) wrote to disk. Best-effort
		# cleanup so repeated test runs don't accumulate stray files.
		for name_hint in TEST_LEAF_FILE_NAMES:
			for is_private in (0, 1):
				path = get_files_path(name_hint, is_private=is_private)
				if os.path.exists(path):
					os.remove(path)

	def _folder(self, name_hint, is_folder, folder=None):
		doc_dict = {
			"doctype": "File",
			"file_name": name_hint,
			"is_folder": is_folder,
			"folder": folder,
			"is_private": 1,
		}
		if not is_folder:
			# A non-folder File needs real backing content: File.validate() ->
			# generate_content_hash() opens the file at file_url and throws if it
			# doesn't exist on disk. Passing `content` makes File.before_insert()
			# write the physical file itself and set file_url accordingly.
			doc_dict["content"] = f"test content for {name_hint}"
		doc = frappe.get_doc(doc_dict).insert(ignore_permissions=True)
		return doc

	def _lft_rgt(self, name):
		row = frappe.db.get_value("File", name, ["lft", "rgt"], as_dict=1)
		return row.lft, row.rgt

	def test_query_count_scales_sublinearly(self):
		"""See the matching comment in test_delete_unneeded_files.py: rebuild_tree()
		scans the whole table and writes in 500-row batched UPDATEs, so on a real
		site with many File rows the query count legitimately scales with
		total_rows / 500, not a fixed constant."""
		chunk_size = 500
		total_files = frappe.db.count("File")
		expected_chunks = (total_files // chunk_size) + 1
		expected_ceiling = 4 + expected_chunks * 2
		with assert_max_queries(expected_ceiling, test_case=self):
			rebuild_tree(doctype="File", parent_field="folder", group_field="is_folder")

	def test_nested_set_containment_and_no_overlap(self):
		rebuild_tree(doctype="File", parent_field="folder", group_field="is_folder")

		root_a_lft, root_a_rgt = self._lft_rgt(self.root_a.name)
		root_b_lft, root_b_rgt = self._lft_rgt(self.root_b.name)
		child_a_lft, child_a_rgt = self._lft_rgt(self.child_a.name)
		leaf_a_lft, leaf_a_rgt = self._lft_rgt(self.leaf_a.name)
		leaf_b_lft, leaf_b_rgt = self._lft_rgt(self.leaf_b.name)

		# Every node: rgt > lft
		for lft, rgt in [(root_a_lft, root_a_rgt), (root_b_lft, root_b_rgt),
						  (child_a_lft, child_a_rgt), (leaf_a_lft, leaf_a_rgt),
						  (leaf_b_lft, leaf_b_rgt)]:
			self.assertGreater(rgt, lft)

		# Containment: child_a and leaf_a fall inside root_a's range
		self.assertGreater(child_a_lft, root_a_lft)
		self.assertLess(child_a_rgt, root_a_rgt)
		self.assertGreater(leaf_a_lft, child_a_lft)
		self.assertLess(leaf_a_rgt, child_a_rgt)

		# Containment: leaf_b falls inside root_b's range
		self.assertGreater(leaf_b_lft, root_b_lft)
		self.assertLess(leaf_b_rgt, root_b_rgt)

		# The two root-level groups must not overlap (this is the bug the
		# rewrite fixed: previously both roots could start at the same lft).
		root_a_range = set(range(root_a_lft, root_a_rgt + 1))
		root_b_range = set(range(root_b_lft, root_b_rgt + 1))
		self.assertEqual(root_a_range & root_b_range, set())

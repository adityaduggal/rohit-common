# -*- coding: utf-8 -*-
# Copyright (c) 2026, Rohit Industries Group Private Limited and Contributors.
# For license information, please see license.txt
from __future__ import unicode_literals

import os
import re
import unittest
from unittest.mock import MagicMock, patch

import frappe
import requests
from frappe.utils import get_files_path, random_string

from rohit_common.rohit_common.validations import google_maps
from rohit_common.utils import email_utils
from rohit_common.utils.query_guard import assert_max_queries
from rohit_common.utils.rohit_common_utils import rebuild_tree, sanitize_dynamic_link


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


class TestAddressContactHooks(unittest.TestCase):
	"""
	Issue #20: Address/Contact saves must not scan the whole Dynamic Link table,
	HTTP calls must time out, and Frappe's Contact for a new User must save.
	requests.get is patched only to stand in for Google Maps and Bouncify.
	"""

	def setUp(self):
		frappe.local.bouncify_credits = None

	def tearDown(self):
		frappe.db.rollback()
		frappe.local.bouncify_credits = None

	@patch.object(email_utils.requests, "get", side_effect=requests.ConnectionError)
	def test_address_save_does_not_scan_dynamic_link(self, _get):
		names = frappe.get_all("Address", filters={"disabled": 0, "country": "India"},
			pluck="name", limit=50)
		# A name with special characters would be renamed, which is a different path
		name = next((n for n in names if re.fullmatch(r"[A-Za-z0-9\-]+", n)), None)
		if not name:
			self.skipTest("No enabled India Address with a plain name on this site")
		adr = frappe.get_doc("Address", name)
		adr.flags.ignore_mandatory = True

		statements = []
		original_sql = frappe.db.sql

		def recording_sql(query, *args, **kwargs):
			statements.append(str(query))
			return original_sql(query, *args, **kwargs)

		with patch.object(frappe.db, "sql", side_effect=recording_sql):
			adr.save()

		scans = [q for q in statements if "Dynamic Link" in q and "NOT IN" in q.upper()]
		self.assertEqual(scans, [])

	def test_daily_cleanup_deletes_only_orphan_links(self):
		orphan = "test-orphan-dl-" + random_string(8)
		frappe.db.sql("""INSERT INTO `tabDynamic Link`
			(name, parent, parenttype, parentfield, link_doctype, link_name)
			VALUES (%(name)s, %(parent)s, 'Address', 'links', 'Customer', 'X')""",
			{"name": orphan, "parent": "no-such-address-" + random_string(8)})
		kept = frappe.db.get_value("Dynamic Link", {"parenttype": "Address"}, "name")
		kept = kept if kept != orphan else None

		with assert_max_queries(4, test_case=self):
			sanitize_dynamic_link()

		self.assertFalse(frappe.db.exists("Dynamic Link", orphan))
		if kept:
			self.assertTrue(frappe.db.exists("Dynamic Link", kept))

	@patch.object(email_utils.requests, "get", side_effect=requests.ConnectionError)
	def test_new_user_gets_its_contact(self, _get):
		email = f"test-n20-{random_string(8).lower()}@example.com"
		frappe.get_doc({"doctype": "User", "email": email, "first_name": "Issue Twenty",
			"send_welcome_email": 0}).insert(ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Contact", {"user": email}))

	@patch.object(google_maps, "get_google_maps_key_url", return_value=("key", "https://maps.test/"))
	@patch.object(google_maps.requests, "get", side_effect=requests.Timeout)
	def test_gmaps_timeout_keeps_the_save_working(self, mock_get, _key):
		reply = google_maps.get_gmaps_json("geocode", "address=+Test")
		self.assertEqual(reply, {"status": "REQUEST_FAILED"})
		self.assertEqual(mock_get.call_args.kwargs["timeout"], google_maps.timeout)

	@patch.object(email_utils, "get_bouncify_api_key", return_value=("key", "https://bouncify.test/"))
	@patch.object(email_utils.requests, "get")
	def test_bouncify_credits_fetched_once_per_request(self, mock_get, _key):
		mock_get.return_value = MagicMock(text='{"success": 0}')
		email_utils.process_bouncify_response("a@example.com")
		email_utils.process_bouncify_response("b@example.com")

		info_calls = [c for c in mock_get.call_args_list if "/info?" in c.args[0]]
		self.assertEqual(len(info_calls), 1)
		for call in mock_get.call_args_list:
			self.assertEqual(call.kwargs["timeout"], email_utils.timeout)

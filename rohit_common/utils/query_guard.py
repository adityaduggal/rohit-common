# -*- coding: utf-8 -*-
# Copyright (c) 2026, Rohit Industries Group Private Limited and Contributors.
# For license information, please see license.txt
from __future__ import unicode_literals

import frappe


class assert_max_queries(object):
	"""Test helper: fails if more than `limit` SQL statements run inside the block.

	Wraps frappe.db.sql for the duration of the `with` block and counts calls.
	Use this to pin down the query count of a batched operation so a future
	edit that reintroduces a per-row query (N+1) fails the test instead of
	silently regressing performance.

	Usage:
		with assert_max_queries(5):
			delete_unneeded_files.check_correct_folders()
	"""

	def __init__(self, limit, test_case=None):
		self.limit = limit
		self.test_case = test_case
		self.count = 0
		self._original_sql = None

	def __enter__(self):
		self._original_sql = frappe.db.sql

		def counting_sql(*args, **kwargs):
			self.count += 1
			return self._original_sql(*args, **kwargs)

		frappe.db.sql = counting_sql
		return self

	def __exit__(self, exc_type, exc_val, exc_tb):
		frappe.db.sql = self._original_sql
		if exc_type is not None:
			# Don't mask the real failure with a query-count assertion.
			return False
		message = "Expected at most {} queries, ran {}".format(self.limit, self.count)
		if self.test_case is not None:
			self.test_case.assertLessEqual(self.count, self.limit, message)
		else:
			assert self.count <= self.limit, message
		return False

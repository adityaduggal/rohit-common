# -*- coding: utf-8 -*-
# Copyright (c) 2026, Rohit Industries Group Private Limited and Contributors.
# For license information, please see license.txt
"""
Only the ERP HTTP call and the ERP login are stubbed. The Sales Invoices and the writes are real,
and are rolled back after each test.

Run: bench --site dev-rb-v12 run-tests --module rohit_common.rohit_common.scheduled_tasks.test_auto_update_from_erp
"""
from __future__ import unicode_literals

import json
import unittest
from unittest.mock import MagicMock, patch

import frappe

from rohit_common.rohit_common.scheduled_tasks import auto_update_from_erp
from rohit_common.rohit_common.scheduled_tasks.auto_update_from_erp import (
	EXPORT_UPDATE_FAILURE_TITLE, update_export_invoices,
)

LOGIN = ("https://erp.example.test", {"Authorization": "token x:y"})
ERP_API = "rohit_common.rohit_common.erpnext_api.erpnext_api_common"


def _response(data=None, not_json=False):
	response = MagicMock()
	if not_json:
		response.json.side_effect = json.JSONDecodeError("Expecting value", "<html>", 0)
	else:
		response.json.return_value = {"data": data}
	return response


class TestUpdateExportInvoices(unittest.TestCase):
	def setUp(self):
		self.invoices = frappe.get_all("Sales Invoice", filters={"docstatus": 1},
			fields=["name", "amended_from", "shipping_bill_number", "shipping_bill_date"], limit=2)
		if len(self.invoices) < 2:
			self.skipTest("Needs 2 submitted Sales Invoices on the site")

	def tearDown(self):
		frappe.db.rollback()

	def _run(self, responses):
		pending = [frappe._dict(name=inv.name, amended_from=None) for inv in self.invoices]
		with patch.object(auto_update_from_erp, "_pending_export_invoices", return_value=pending), \
				patch.object(auto_update_from_erp, "get_login_details", return_value=LOGIN), \
				patch(ERP_API + ".get_login_details", return_value=LOGIN), \
				patch(ERP_API + ".requests.get", side_effect=responses) as mock_get:
			update_export_invoices()
		return mock_get

	def test_non_json_response_continues_with_next_invoice(self):
		first, second = self.invoices
		mock_get = self._run([
			_response(not_json=True),
			_response([{"name": second.name, "shipping_bill_number": "SB-22-TEST",
				"shipping_bill_date": "2026-10-01"}]),
		])

		self.assertEqual(mock_get.call_count, 2)
		updated = frappe.db.get_value("Sales Invoice", second.name,
			["shipping_bill_number", "shipping_bill_date"], as_dict=1)
		self.assertEqual(updated.shipping_bill_number, "SB-22-TEST")
		self.assertEqual(str(updated.shipping_bill_date), "2026-10-01")
		self.assertEqual(frappe.db.get_value("Sales Invoice", first.name, "shipping_bill_number"),
			first.shipping_bill_number)

		error = frappe.get_all("Error Log", filters={"method": EXPORT_UPDATE_FAILURE_TITLE},
			fields=["error"], order_by="creation desc", limit=1)
		self.assertTrue(error)
		self.assertIn(f"{first.name}: JSONDecodeError", error[0].error)

	def test_remote_row_without_shipping_bill_is_not_written(self):
		first, second = self.invoices
		self._run([
			_response([{"name": first.name, "shipping_bill_number": None, "shipping_bill_date": None}]),
			_response([]),
		])

		self.assertEqual(frappe.db.get_value("Sales Invoice", first.name, "shipping_bill_number"),
			first.shipping_bill_number)

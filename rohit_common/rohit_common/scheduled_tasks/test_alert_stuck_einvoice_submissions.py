#  Copyright (c) 2026. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
"""
Unit tests for alert_stuck_einvoice_submissions.py (T12,
docs/designs/gst-asp-migration-whitebooks.md) — stuck-entry query filtering
and the alert-on/alert-off branches. All mocked (frappe) — no live site or
WhiteBooks credentials required.

Run: <bench-root>/env/bin/python -m pytest rohit_common/rohit_common/scheduled_tasks/test_alert_stuck_einvoice_submissions.py -v
"""
import unittest
from unittest.mock import patch

from frappe import _dict

from rohit_common.rohit_common.scheduled_tasks import alert_stuck_einvoice_submissions as task


class TestExecute(unittest.TestCase):
    @patch("rohit_common.rohit_common.scheduled_tasks.alert_stuck_einvoice_submissions.frappe")
    def test_no_stuck_entries_is_a_noop(self, mock_frappe):
        mock_frappe.get_all.return_value = []

        task.execute()

        mock_frappe.log_error.assert_not_called()

    @patch("rohit_common.rohit_common.scheduled_tasks.alert_stuck_einvoice_submissions.frappe")
    def test_stuck_entries_trigger_a_single_consolidated_alert(self, mock_frappe):
        mock_frappe.get_all.return_value = [
            _dict(
                name="EISL-0001",
                reference_doctype="Sales Invoice",
                reference_name="SINV-0001",
                submission_id="sub-1",
                submitted_on="2026-08-22 00:00:00",
            ),
            _dict(
                name="EISL-0002",
                reference_doctype="Sales Invoice",
                reference_name="SINV-0002",
                submission_id="sub-2",
                submitted_on="2026-08-22 00:05:00",
            ),
        ]

        task.execute()

        mock_frappe.log_error.assert_called_once()
        _, kwargs = mock_frappe.log_error.call_args
        self.assertIn("EISL-0001", kwargs["message"])
        self.assertIn("EISL-0002", kwargs["message"])
        self.assertIn("2", kwargs["message"])

    @patch("rohit_common.rohit_common.scheduled_tasks.alert_stuck_einvoice_submissions.frappe")
    def test_query_filters_to_backlog_submitted_older_than_threshold(self, mock_frappe):
        mock_frappe.get_all.return_value = []

        task.execute()

        _, kwargs = mock_frappe.get_all.call_args
        self.assertEqual(kwargs["filters"]["submission_path"], "Backlog")
        self.assertEqual(kwargs["filters"]["status"], "Submitted")
        self.assertEqual(kwargs["filters"]["submitted_on"][0], "<")


if __name__ == "__main__":
    unittest.main()

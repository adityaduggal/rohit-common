#  Copyright (c) 2026. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
"""
Unit tests for auto_einvoice_tasks.py's WhiteBooks live-path functions (T10,
docs/designs/gst-asp-migration-whitebooks.md) — applicability gating,
enqueue wiring, and the job body's error handling. All mocked (frappe,
enqueue, generate_irn_whitebooks) — no live site or WhiteBooks credentials
required.

generate_irn_whitebooks() itself (T3) is unverified against a real
WhiteBooks sandbox response — these tests only prove the live-path wrapper
around it behaves correctly, not that a real submission would succeed.

Run: <bench-root>/env/bin/python -m pytest rohit_common/rohit_common/scheduled_tasks/test_auto_einvoice_tasks.py -v
"""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from rohit_common.rohit_common.scheduled_tasks import auto_einvoice_tasks as tasks


class TestLiveEinvoiceApplicable(unittest.TestCase):
    @patch("rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks.einv_needed")
    @patch("rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks.frappe")
    def test_not_applicable_when_einvoice_disabled(self, mock_frappe, mock_einv_needed):
        mock_frappe.get_value.side_effect = [0, "2026-01-01"]  # enable_einvoice, applicable_date
        doc = SimpleNamespace(doctype="Sales Invoice", name="SINV-0001", posting_date="2026-08-22")

        self.assertFalse(tasks._live_einvoice_applicable(doc))
        mock_einv_needed.assert_not_called()

    @patch("rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks.einv_needed")
    @patch("rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks.frappe")
    def test_not_applicable_before_applicable_date(self, mock_frappe, mock_einv_needed):
        mock_frappe.get_value.side_effect = [1, "2027-01-01"]
        doc = SimpleNamespace(doctype="Sales Invoice", name="SINV-0001", posting_date="2026-08-22")

        self.assertFalse(tasks._live_einvoice_applicable(doc))
        mock_einv_needed.assert_not_called()

    @patch("rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks.einv_needed")
    @patch("rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks.frappe")
    def test_applicable_when_enabled_after_date_and_einv_needed(self, mock_frappe, mock_einv_needed):
        mock_frappe.get_value.side_effect = [1, "2026-01-01"]
        mock_einv_needed.return_value = 1
        doc = SimpleNamespace(doctype="Sales Invoice", name="SINV-0001", posting_date="2026-08-22")

        self.assertTrue(tasks._live_einvoice_applicable(doc))
        mock_einv_needed.assert_called_once_with("Sales Invoice", "SINV-0001")

    @patch("rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks.einv_needed")
    @patch("rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks.frappe")
    def test_not_applicable_when_einv_needed_returns_zero(self, mock_frappe, mock_einv_needed):
        mock_frappe.get_value.side_effect = [1, "2026-01-01"]
        mock_einv_needed.return_value = 0
        doc = SimpleNamespace(doctype="Sales Invoice", name="SINV-0001", posting_date="2026-08-22")

        self.assertFalse(tasks._live_einvoice_applicable(doc))

    @patch("rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks.einv_needed")
    @patch("rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks.frappe")
    def test_no_applicable_date_configured_does_not_block(self, mock_frappe, mock_einv_needed):
        mock_frappe.get_value.side_effect = [1, None]
        mock_einv_needed.return_value = 1
        doc = SimpleNamespace(doctype="Sales Invoice", name="SINV-0001", posting_date="2020-01-01")

        self.assertTrue(tasks._live_einvoice_applicable(doc))


class TestQueueLiveEinvoiceSubmission(unittest.TestCase):
    @patch("rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks.enqueue")
    @patch("rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks._live_einvoice_applicable")
    def test_enqueues_on_short_queue_when_applicable(self, mock_applicable, mock_enqueue):
        mock_applicable.return_value = True
        doc = SimpleNamespace(doctype="Sales Invoice", name="SINV-0001")

        tasks.queue_live_einvoice_submission(doc)

        mock_enqueue.assert_called_once()
        call = mock_enqueue.call_args
        self.assertEqual(call.args[0], tasks.submit_live_einvoice_whitebooks)
        self.assertEqual(call.kwargs["queue"], "short")
        self.assertEqual(call.kwargs["dtype"], "Sales Invoice")
        self.assertEqual(call.kwargs["dname"], "SINV-0001")

    @patch("rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks.enqueue")
    @patch("rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks._live_einvoice_applicable")
    def test_does_not_enqueue_when_not_applicable(self, mock_applicable, mock_enqueue):
        mock_applicable.return_value = False
        doc = SimpleNamespace(doctype="Sales Invoice", name="SINV-0001")

        tasks.queue_live_einvoice_submission(doc)

        mock_enqueue.assert_not_called()

    @patch("rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks.enqueue")
    @patch("rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks._live_einvoice_applicable")
    def test_accepts_method_kwarg_from_doc_event_signature(self, mock_applicable, mock_enqueue):
        """doc_events call handlers as fn(doc, method) - must not raise
        TypeError on the extra positional/keyword arg."""
        mock_applicable.return_value = False
        doc = SimpleNamespace(doctype="Sales Invoice", name="SINV-0001")

        tasks.queue_live_einvoice_submission(doc, method="on_submit")  # must not raise


class TestSubmitLiveEinvoiceWhitebooks(unittest.TestCase):
    @patch("rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks.generate_irn_whitebooks")
    def test_calls_generate_irn_whitebooks(self, mock_generate):
        tasks.submit_live_einvoice_whitebooks("Sales Invoice", "SINV-0001")

        mock_generate.assert_called_once_with("Sales Invoice", "SINV-0001")

    @patch("rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks.frappe")
    @patch("rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks.generate_irn_whitebooks")
    def test_logs_and_reraises_on_failure(self, mock_generate, mock_frappe):
        mock_generate.side_effect = RuntimeError("WhiteBooks 500")

        with self.assertRaises(RuntimeError):
            tasks.submit_live_einvoice_whitebooks("Sales Invoice", "SINV-0001")

        mock_frappe.log_error.assert_called_once()
        log_call = mock_frappe.log_error.call_args
        self.assertIn("SINV-0001", log_call.kwargs["message"])


class TestMakeEinvoiceForDocsWhitebooksBulk(unittest.TestCase):
    @patch("rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks.generate_irn_whitebooks_bulk")
    @patch("rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks.frappe")
    def test_returns_zero_zero_when_einvoicing_disabled(self, mock_frappe, mock_bulk):
        mock_frappe.get_value.return_value = 0

        result = tasks.make_einvoice_for_docs_whitebooks_bulk()

        self.assertEqual(result, {"submitted": 0, "rejected": 0})
        mock_bulk.assert_not_called()

    @patch("rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks.generate_irn_whitebooks_bulk")
    @patch("rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks.frappe")
    def test_returns_zero_zero_when_no_pending_docs(self, mock_frappe, mock_bulk):
        mock_frappe.get_value.side_effect = [1, "2026-01-01"]
        mock_frappe.db.sql.return_value = []

        result = tasks.make_einvoice_for_docs_whitebooks_bulk()

        self.assertEqual(result, {"submitted": 0, "rejected": 0})
        mock_bulk.assert_not_called()

    @patch("rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks.einv_needed")
    @patch("rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks.generate_irn_whitebooks_bulk")
    @patch("rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks.frappe")
    def test_partial_batch_creates_correct_log_entries_for_each(
        self, mock_frappe, mock_bulk, mock_einv_needed
    ):
        """Guards the partial-batch-failure requirement end to end: one
        accepted (Submitted), one rejected (Failed with error), in the same
        run — not all-or-nothing."""
        mock_frappe.get_value.side_effect = [1, "2026-01-01"]
        mock_frappe.db.sql.return_value = [
            SimpleNamespace(name="SINV-1"),
            SimpleNamespace(name="SINV-2"),
        ]
        mock_einv_needed.return_value = 1
        mock_bulk.return_value = (
            {"SINV-1": "sid-1", "SINV-2": "sid-2"},
            {"SINV-2": "Invalid GSTIN"},
        )
        mock_frappe.get_single.return_value = SimpleNamespace(sandbox_mode=1)
        created_docs = []
        mock_frappe.get_doc.side_effect = lambda d: created_docs.append(d) or MagicMock()

        result = tasks.make_einvoice_for_docs_whitebooks_bulk()

        self.assertEqual(result, {"submitted": 1, "rejected": 1})
        self.assertEqual(len(created_docs), 2)
        sinv1_log = next(d for d in created_docs if d["reference_name"] == "SINV-1")
        sinv2_log = next(d for d in created_docs if d["reference_name"] == "SINV-2")
        self.assertEqual(sinv1_log["status"], "Submitted")
        self.assertIsNone(sinv1_log["error_message"])
        self.assertEqual(sinv2_log["status"], "Failed")
        self.assertEqual(sinv2_log["error_message"], "Invalid GSTIN")
        self.assertEqual(sinv1_log["submission_path"], "Backlog")
        self.assertEqual(sinv1_log["environment"], "Sandbox")
        mock_frappe.db.commit.assert_called_once()

    @patch("rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks.einv_needed")
    @patch("rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks.generate_irn_whitebooks_bulk")
    @patch("rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks.frappe")
    def test_rejected_invoice_logs_error(self, mock_frappe, mock_bulk, mock_einv_needed):
        mock_frappe.get_value.side_effect = [1, "2026-01-01"]
        mock_frappe.db.sql.return_value = [SimpleNamespace(name="SINV-1")]
        mock_einv_needed.return_value = 1
        mock_bulk.return_value = ({"SINV-1": "sid-1"}, {"SINV-1": "Invalid GSTIN"})
        mock_frappe.get_single.return_value = SimpleNamespace(sandbox_mode=1)
        mock_frappe.get_doc.return_value = MagicMock()

        tasks.make_einvoice_for_docs_whitebooks_bulk()

        mock_frappe.log_error.assert_called_once()
        self.assertIn("SINV-1", mock_frappe.log_error.call_args.kwargs["message"])

    @patch("rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks.einv_needed")
    @patch("rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks.generate_irn_whitebooks_bulk")
    @patch("rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks.frappe")
    def test_filters_out_docs_where_einv_not_needed(self, mock_frappe, mock_bulk, mock_einv_needed):
        mock_frappe.get_value.side_effect = [1, "2026-01-01"]
        mock_frappe.db.sql.return_value = [
            SimpleNamespace(name="SINV-1"),
            SimpleNamespace(name="SINV-2"),
        ]
        mock_einv_needed.side_effect = [1, 0]  # SINV-1 needed, SINV-2 not
        mock_bulk.return_value = ({"SINV-1": "sid-1"}, {})
        mock_frappe.get_single.return_value = SimpleNamespace(sandbox_mode=0)
        mock_frappe.get_doc.return_value = MagicMock()

        tasks.make_einvoice_for_docs_whitebooks_bulk()

        mock_bulk.assert_called_once_with("Sales Invoice", ["SINV-1"])


if __name__ == "__main__":
    unittest.main()

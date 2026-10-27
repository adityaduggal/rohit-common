#  Copyright (c) 2026. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
"""
Unit tests for auto_einvoice_tasks.py's live path (on_submit → short queue →
generate_irn): applicability gating, enqueue wiring, and the job body's error
handling. All mocked (frappe, enqueue, generate_irn). The site tests for the
15-min sweeps are further down.

Run: bench --site dev-rb-v12 run-tests --module rohit_common.rohit_common.scheduled_tasks.test_auto_einvoice_tasks
"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

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
        self.assertEqual(call.args[0], tasks.submit_live_einvoice)
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


class TestSubmitLiveEinvoice(unittest.TestCase):
    @patch("rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks.generate_irn")
    def test_calls_generate_irn(self, mock_generate):
        tasks.submit_live_einvoice("Sales Invoice", "SINV-0001")

        mock_generate.assert_called_once_with("Sales Invoice", "SINV-0001")

    @patch("rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks.frappe")
    @patch("rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks.generate_irn")
    def test_logs_with_the_sweep_title_and_reraises(self, mock_generate, mock_frappe):
        """The sweep backs off an invoice whose failure is logged under EINV_FAILURE_TITLE."""
        mock_generate.side_effect = RuntimeError("WhiteBooks 500")
        mock_frappe.get_traceback.return_value = "Traceback"

        with self.assertRaises(RuntimeError):
            tasks.submit_live_einvoice("Sales Invoice", "SINV-0001")

        mock_frappe.db.rollback.assert_called_once()
        self.assertEqual(mock_frappe.log_error.call_args.args[1], tasks.EINV_FAILURE_TITLE + "SINV-0001")


# ---------------------------------------------------------------------------
# #16: long-queue sweeps. These run against real rows on the site. Only the
# queue, commit/rollback and the submit/save/API call are patched. Every test
# rolls back.
#
# Run: bench --site <sitename> run-tests --module rohit_common.rohit_common.scheduled_tasks.test_auto_einvoice_tasks
# ---------------------------------------------------------------------------
import frappe
from frappe.utils import getdate, now_datetime
from rq.timeouts import JobTimeoutException

from rohit_common.utils import background_doc_processing as bg

TASKS = "rohit_common.rohit_common.scheduled_tasks.auto_einvoice_tasks"
BG = "rohit_common.utils.background_doc_processing"


class SiteTestCase(unittest.TestCase):
    """Patches commit/rollback so a test sees its own writes, then really rolls back.
    Error Log is a MyISAM table, so a rollback keeps its rows. tearDown deletes the
    rows these tests write, else the 24 hour eInvoice back-off sees them on the next run."""

    def setUp(self):
        self.started = now_datetime()
        self.real_rollback = frappe.db.rollback
        self.real_rollback()
        for name in ("commit", "rollback"):
            patcher = patch.object(frappe.db, name)
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        self.real_rollback()
        for title in ("Auto %", tasks.EINV_FAILURE_TITLE + "%"):
            frappe.db.delete("Error Log", {"creation": [">=", self.started], "method": ["like", title]})

    def get_draft_invoice(self):
        name = frappe.db.get_value("Sales Invoice", {"docstatus": 0})
        if not name:
            self.skipTest("Needs one draft Sales Invoice")
        return name

    def get_comments(self, name, action):
        return frappe.get_all("Comment", pluck="content", filters={"reference_doctype": "Sales Invoice",
            "reference_name": name, "content": ["like", f"Auto {action} failed:%"]})


class TestEnqueueOnce(unittest.TestCase):
    def test_second_call_does_not_enqueue_while_first_is_queued(self):
        queued = []
        with patch(f"{BG}.enqueue", side_effect=lambda method, **kw: queued.append(kw["job_name"])), \
                patch(f"{BG}.get_jobs", side_effect=lambda **kw: {frappe.local.site: list(queued)}):
            tasks.enq_inv_sub()
            tasks.enq_inv_sub()
        self.assertEqual(queued, [f"{TASKS}.get_docs_to_submit"])

    def test_cron_enqueuers_use_dotted_paths_as_job_name(self):
        with patch(f"{BG}.enqueue") as mock_enqueue, patch(f"{BG}.get_jobs", return_value={}):
            tasks.enq_einv_create()
            bg.enqueue_bg()
        names = [call.kwargs["job_name"] for call in mock_enqueue.call_args_list]
        self.assertEqual(names, [f"{TASKS}.make_einvoice_for_docs", f"{BG}.process_bg_docs"])
        for name in names:
            self.assertTrue(callable(frappe.get_attr(name)))


class TestGetDocsToSubmit(SiteTestCase):
    def test_failed_draft_is_unmarked_commented_logged_and_not_retried(self):
        name = self.get_draft_invoice()
        frappe.db.set_value("Sales Invoice", name, "marked_to_submit", 1, update_modified=False)
        error = frappe.ValidationError("<b>Stock</b> not available for item X")
        with patch("frappe.model.document.Document.submit", side_effect=error) as mock_submit:
            tasks.get_docs_to_submit()
            self.assertEqual(frappe.db.get_value("Sales Invoice", name, "marked_to_submit"), 0)
            tasks.get_docs_to_submit()
        self.assertEqual(mock_submit.call_count, 1)
        comments = self.get_comments(name, "submit")
        self.assertEqual(len(comments), 1)
        self.assertIn("Stock not available for item X", comments[0])
        self.assertLessEqual(len(comments[0]), 300)
        self.assertTrue(frappe.db.exists("Error Log", {"method": f"Auto submit Failed for Sales Invoice {name}"}))

    def test_job_timeout_is_not_swallowed(self):
        name = self.get_draft_invoice()
        frappe.db.set_value("Sales Invoice", name, "marked_to_submit", 1, update_modified=False)
        with patch("frappe.model.document.Document.submit", side_effect=JobTimeoutException("timeout")):
            with self.assertRaises(JobTimeoutException):
                tasks.get_docs_to_submit()
        self.assertEqual(frappe.db.get_value("Sales Invoice", name, "marked_to_submit"), 1)

    def test_stops_when_time_budget_is_used(self):
        name = self.get_draft_invoice()
        frappe.db.set_value("Sales Invoice", name, "marked_to_submit", 1, update_modified=False)
        with patch(f"{TASKS}.SWEEP_TIME_BUDGET", -1), \
                patch("frappe.model.document.Document.submit") as mock_submit:
            tasks.get_docs_to_submit()
        mock_submit.assert_not_called()


class TestProcessBgDocs(SiteTestCase):
    def test_failed_doc_is_unmarked_and_does_not_stop_the_job(self):
        name = self.get_draft_invoice()
        frappe.db.set_value("Sales Invoice", name, "background_processing", 1, update_modified=False)
        with patch(f"{BG}.get_bg_docs", return_value=["Sales Invoice"]), \
                patch("frappe.model.document.Document.save", side_effect=frappe.ValidationError("Bad row")):
            bg.process_bg_docs()  # must not raise
        self.assertEqual(frappe.db.get_value("Sales Invoice", name, "background_processing"), 0)
        self.assertEqual(len(self.get_comments(name, "submit")), 1)
        self.assertTrue(frappe.db.exists("Error Log", {"method": f"Auto submit Failed for Sales Invoice {name}"}))


class TestMakeEinvoiceForDocs(SiteTestCase):
    def setUp(self):
        """Uses the site's real einvoice_applicable_date. One real registered invoice on or
        after that date loses its IRN inside the rolled-back transaction, so it is pending."""
        super().setUp()
        self.einv_date = frappe.db.get_single_value("Rohit Settings", "einvoice_applicable_date")
        if not self.einv_date:
            self.skipTest("Needs einvoice_applicable_date in Rohit Settings")
        frappe.db.set_value("Rohit Settings", "Rohit Settings", "enable_einvoice", 1)
        made_pending = frappe.get_all("Sales Invoice", pluck="name", order_by="posting_date desc",
            filters={"docstatus": 1, "posting_date": [">=", self.einv_date], "irn": ["is", "set"],
                "gst_category": ["not in", ["Unregistered"]],
                "name": ["not in", tasks._recent_einvoice_failures() or [""]]}, limit=1)
        if not made_pending:
            self.skipTest("Needs a submitted registered Sales Invoice with an IRN after the applicable date")
        frappe.db.set_value("Sales Invoice", made_pending[0], "irn", None, update_modified=False)
        self.pending = tasks._find_pending_einvoice_docs(self.einv_date,
            exclude=tasks._recent_einvoice_failures(), limit=3)
        self.assertIn(made_pending[0], [d.name for d in self.pending])

    def test_pending_query_skips_unregistered_old_and_excluded(self):
        rows = tasks._find_pending_einvoice_docs(self.einv_date, limit=50)
        details = frappe.get_all("Sales Invoice", fields=["gst_category", "posting_date"],
            filters={"name": ["in", [d.name for d in rows]]})
        self.assertNotIn("Unregistered", {d.gst_category for d in details})
        self.assertTrue(all(d.posting_date >= getdate(self.einv_date) for d in details))
        first = self.pending[0].name
        rest = tasks._find_pending_einvoice_docs(self.einv_date, exclude=[first], limit=50)
        self.assertNotIn(first, [d.name for d in rest])

    def test_just_submitted_invoice_is_left_to_the_live_job(self):
        first = self.pending[0].name
        frappe.db.set_value("Sales Invoice", first, "modified", now_datetime(), update_modified=False)
        rows = tasks._find_pending_einvoice_docs(self.einv_date, limit=50)
        self.assertNotIn(first, [d.name for d in rows])

    def test_failed_invoice_is_logged_and_skipped_on_next_run(self):
        with patch(f"{TASKS}.EINV_BATCH_SIZE", 3), \
                patch(f"{TASKS}.einv_needed") as mock_needed, \
                patch(f"{TASKS}.generate_irn", side_effect=frappe.ValidationError("Invalid GSTIN")) as mock_irn:
            tasks.make_einvoice_for_docs()
            first_run = [call.kwargs["dname"] for call in mock_irn.call_args_list]
            mock_irn.reset_mock()
            tasks.make_einvoice_for_docs()
            second_run = [call.kwargs["dname"] for call in mock_irn.call_args_list]
        mock_needed.assert_not_called()
        self.assertEqual(first_run, [d.name for d in self.pending])
        self.assertFalse(set(first_run) & set(second_run))
        for name in first_run:
            self.assertTrue(frappe.db.exists("Error Log", {"method": tasks.EINV_FAILURE_TITLE + name}))

    def test_request_error_log_does_not_contain_the_url(self):
        secret_url = "https://gstapi.example.com/x?aspid=1&password=SECRET"
        error = tasks.requests.ConnectionError(f"Max retries exceeded with url: {secret_url}")
        with patch(f"{TASKS}.EINV_BATCH_SIZE", 1), patch(f"{TASKS}.generate_irn", side_effect=error):
            tasks.make_einvoice_for_docs()
        logged = frappe.db.get_value("Error Log", {"method": tasks.EINV_FAILURE_TITLE + self.pending[0].name},
            "error")
        self.assertIn("ConnectionError", logged)
        self.assertNotIn("SECRET", logged)


if __name__ == "__main__":
    unittest.main()

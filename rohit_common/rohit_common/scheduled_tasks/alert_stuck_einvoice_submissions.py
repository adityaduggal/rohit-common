# -*- coding: utf-8 -*-
# Copyright (c) 2026, Rohit Industries Group Private Limited and Contributors.
# For license information, please see license.txt

"""
T12, docs/designs/gst-asp-migration-whitebooks.md — the alerting
requirement that was originally flagged as having no implementation hook
(plan-eng-review finding: "would have shipped dormant"). Scope is
backlog-path only, per the T10/Approach C revision — the live path (T10)
is synchronous with no async gap, so there's nothing for it to get "stuck"
in; only backlog-path E-Invoice Submission Log entries can sit in
`Submitted` waiting for a webhook result that never arrives.

A backlog entry sitting unresolved for a while after submission is not
inherently wrong (WhiteBooks may take longer to process a bulk batch than
a single invoice), but past STUCK_THRESHOLD_MINUTES it's worth a human
looking at — either the webhook never fired (push-vs-poll, T2, still
unconfirmed) or something else is wrong.
"""

from __future__ import unicode_literals
import frappe
from frappe.utils import add_to_date, now_datetime

STUCK_THRESHOLD_MINUTES = 30


def execute():
    cutoff = add_to_date(now_datetime(), minutes=-STUCK_THRESHOLD_MINUTES)
    stuck = frappe.get_all(
        "E-Invoice Submission Log",
        filters={
            "submission_path": "Backlog",
            "status": "Submitted",
            "submitted_on": ["<", cutoff],
        },
        fields=["name", "reference_doctype", "reference_name", "submission_id", "submitted_on"],
    )
    if not stuck:
        return

    frappe.log_error(
        title="WhiteBooks backlog e-invoice submissions stuck",
        message=(
            f"{len(stuck)} backlog-path E-Invoice Submission Log entries have been "
            f"'Submitted' for more than {STUCK_THRESHOLD_MINUTES} minutes with no "
            f"webhook result: {[s.name for s in stuck]}. Either the webhook never "
            "fired (see the push-vs-poll open question in docs/designs/"
            "gst-asp-migration-whitebooks.md) or something else is wrong — this "
            "does not resolve automatically, it needs a human to look."
        ),
    )

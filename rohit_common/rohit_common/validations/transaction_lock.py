# -*- coding: utf-8 -*-
# Copyright (c) 2026, Rohit Industries Group Private Limited and Contributors.
# For license information, please see license.txt

from __future__ import unicode_literals
import re
import frappe
from frappe.utils import add_days, flt, getdate, nowdate

# Single source of truth for which doctypes participate in the transaction
# view-lock and which field on each holds the transaction date. Rohit
# Settings.locked_doctypes only decides WHICH of these are actually enforced
# and for how many days — a doctype not listed here can't be locked no
# matter what an admin puts in Rohit Settings, because there is no
# has_permission/permission_query_conditions hook registered for it in
# hooks.py. Adding a new lockable doctype means adding it here AND wiring
# hooks.py (see hooks.py comment above the has_permission/
# permission_query_conditions dicts).
LOCKED_DOCTYPE_DATE_FIELDS = {
    "Sales Invoice": "posting_date",
    "Purchase Invoice": "posting_date",
    "POS Invoice": "posting_date",
    "Journal Entry": "posting_date",
    "Payment Entry": "posting_date",
    "GL Entry": "posting_date",
    "Delivery Note": "posting_date",
    "Purchase Receipt": "posting_date",
    "Stock Entry": "posting_date",
    "Quotation": "transaction_date",
    "Sales Order": "transaction_date",
    "Purchase Order": "transaction_date",
}

# "field op value" — the only grammar accepted for
# Rohit Settings.locked_doctypes.doctype_conditions. Anything else is
# rejected at save time by RohitSettings.validate_lock_conditions().
CONDITION_RE = re.compile(r"^(\w+)\s*(!=|=(?!=)|>|<|is)\s*(.+)$")

# The value group above is intentionally greedy (values can legitimately
# contain spaces, e.g. a quoted string) but that means it will also swallow
# a smuggled second clause, e.g. "outstanding_amount != 0 OR status =
# 'Draft'" parses as field=outstanding_amount, op=!=, value="0 OR status =
# 'Draft'" - not a parse failure, just a single (nonsensical, mismatching)
# string comparison. That's not a SQL-injection hole (frappe.db.escape()
# quotes the whole garbage value as one literal either way), but it lets a
# compound condition through silently instead of failing validation at
# save time the way the single-condition grammar is meant to. Reject any
# value containing another comparison operator or a boolean keyword.
_DISALLOWED_VALUE_PATTERN = re.compile(r"(?i)\b(and|or)\b|!=|[<>]|(?<!\\)=")


def parse_condition(condition):
    """
    Parse a "field op value" condition string into (field, op, value).
    Returns None if the string doesn't match the allowed grammar.
    """
    if not condition:
        return None
    match = CONDITION_RE.match(condition.strip())
    if not match:
        return None
    if _DISALLOWED_VALUE_PATTERN.search(match.group(3)):
        return None
    field, op, value = match.group(1), match.group(2), match.group(3).strip()
    if op == "is" and value.lower() not in ("none", "null"):
        # "is" only has a well-defined meaning here as a null-check. Values
        # other than None/null were previously accepted and silently
        # compared by truthiness (bool(doc_value) == bool(coerced)) in
        # condition_holds, and would raise a MySQL syntax error in
        # condition_sql (`IS` only accepts NULL/TRUE/FALSE/UNKNOWN, not
        # arbitrary values) - reject at parse time instead of failing at
        # either of those two points, inconsistently, later.
        return None
    return field, op, value


def _coerce_value(value):
    v = value.strip()
    if v.lower() in ("none", "null"):
        return None
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1]
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        return v


def condition_holds(doc, field, op, value):
    """Evaluate a parsed condition against a loaded Document (single-doc path)."""
    coerced = _coerce_value(value)
    doc_value = doc.get(field)
    if op == "=":
        return doc_value == coerced
    if op == "!=":
        return doc_value != coerced
    if op == ">":
        return flt(doc_value) > flt(coerced)
    if op == "<":
        return flt(doc_value) < flt(coerced)
    if op == "is":
        # parse_condition only lets "is" through paired with None/null.
        return doc_value is None
    return False


def condition_sql(doctype, field, op, value):
    """
    Build a SQL fragment for a parsed condition (list-view / report path).
    permission_query_conditions hooks return a raw string with no separate
    params channel (see frappe.model.db_query.DatabaseQuery.
    get_permission_query_conditions) — values are inlined via
    frappe.db.escape(), matching how Frappe's own core hooks
    (e.g. core.doctype.event.event.get_permission_query_conditions) do it.
    """
    coerced = _coerce_value(value)
    column = f"`tab{doctype}`.`{field}`"
    if op == "is":
        # parse_condition only lets "is" through paired with None/null -
        # MySQL's IS only accepts NULL/TRUE/FALSE/UNKNOWN, not arbitrary
        # values, so there is no other case to handle here.
        return f"{column} IS NULL"
    return f"{column} {op} {frappe.db.escape(coerced)}"


def is_admin_exempt(user):
    """Administrator and System Manager are never subject to the lock."""
    if user == "Administrator":
        return True
    return "System Manager" in frappe.get_roles(user)


def has_bypass_role(user):
    bypass_role = frappe.get_cached_doc("Rohit Settings").transaction_lock_bypass_role
    if not bypass_role:
        return False
    return bypass_role in frappe.get_roles(user)


def get_lock_row(doctype):
    settings = frappe.get_cached_doc("Rohit Settings")
    for row in settings.locked_doctypes:
        if row.document_type == doctype:
            return row
    return None


def is_locked(doc):
    """
    True if `doc` falls outside its doctype's configured retention window
    and no doctype_conditions exception applies. Doctypes with no
    LOCKED_DOCTYPE_DATE_FIELDS entry, or no Rohit Settings row, are never
    locked.
    """
    date_field = LOCKED_DOCTYPE_DATE_FIELDS.get(doc.doctype)
    if not date_field:
        return False
    row = get_lock_row(doc.doctype)
    if not row or not row.days_to_keep:
        return False
    doc_date = doc.get(date_field)
    if not doc_date:
        return False
    cutoff = add_days(nowdate(), -int(row.days_to_keep))
    if getdate(doc_date) > getdate(cutoff):
        return False
    if row.doctype_conditions:
        parsed = parse_condition(row.doctype_conditions)
        if parsed and condition_holds(doc, *parsed):
            return False
    return True


def log_bypass_access(doc, user):
    frappe.get_doc(
        {
            "doctype": "Transaction Lock Access Log",
            "user": user,
            "reference_doctype": doc.doctype,
            "reference_name": doc.name,
        }
    ).insert(ignore_permissions=True)


def has_permission(doc, ptype=None, user=None):
    """
    Registered in hooks.py for every doctype in LOCKED_DOCTYPE_DATE_FIELDS.
    Returning None means "no opinion" — normal role-based permissions decide.
    Only an explicit False actually blocks access.
    """
    user = user or frappe.session.user
    if is_admin_exempt(user):
        return None
    if not is_locked(doc):
        return None
    if has_bypass_role(user):
        log_bypass_access(doc, user)
        return None
    return False


def _permission_query_condition(doctype, user):
    if is_admin_exempt(user):
        return ""
    date_field = LOCKED_DOCTYPE_DATE_FIELDS.get(doctype)
    if not date_field:
        return ""
    row = get_lock_row(doctype)
    if not row or not row.days_to_keep:
        return ""
    if has_bypass_role(user):
        return ""
    cutoff = add_days(nowdate(), -int(row.days_to_keep))
    condition = f"(`tab{doctype}`.`{date_field}` > {frappe.db.escape(cutoff)}"
    if row.doctype_conditions:
        parsed = parse_condition(row.doctype_conditions)
        if parsed:
            condition += f" OR {condition_sql(doctype, *parsed)}"
    condition += ")"
    return condition


# One get_permission_query_conditions_<doctype> function per locked doctype,
# generated here rather than hand-written 12 times. Frappe's
# permission_query_conditions hook resolves each hooks.py entry via
# frappe.get_attr (a plain getattr on this module), calling it with only
# `user` — the doctype isn't passed in, so each doctype needs its own named
# entry point; hooks.py wires each one explicitly by name (static literals,
# no loop there) so the app's hook wiring stays a plain, greppable dict.
def _make_permission_query_conditions(doctype):
    def _fn(user):
        return _permission_query_condition(doctype, user)

    return _fn


def get_voucher_type_lock_condition(sle_alias, voucher_type_field, date_field, user):
    """
    Parameterized SQL condition for reports that mix several voucher types
    in one ledger table (e.g. Stock Ledger Entry, keyed by voucher_type)
    rather than querying a single locked doctype directly. Excludes rows
    whose voucher_type is locked and dated on/before that voucher type's
    retention cutoff.

    Does not evaluate doctype_conditions exceptions — those need a loaded
    Document, not a ledger row. A locked-but-otherwise-exception-eligible
    voucher is hidden here even though opening that same document directly
    still honors its exception via has_permission().
    """
    if is_admin_exempt(user) or has_bypass_role(user):
        return "", {}
    clauses = []
    values = {}
    settings = frappe.get_cached_doc("Rohit Settings")
    for idx, row in enumerate(settings.locked_doctypes):
        if row.document_type not in LOCKED_DOCTYPE_DATE_FIELDS or not row.days_to_keep:
            continue
        vt_key = f"lock_vt_{idx}"
        cutoff_key = f"lock_cutoff_{idx}"
        values[vt_key] = row.document_type
        values[cutoff_key] = add_days(nowdate(), -int(row.days_to_keep))
        clauses.append(
            f"({sle_alias}.{voucher_type_field} = %({vt_key})s "
            f"AND {sle_alias}.{date_field} <= %({cutoff_key})s)"
        )
    if not clauses:
        return "", {}
    return " AND NOT (" + " OR ".join(clauses) + ")", values


for _doctype in LOCKED_DOCTYPE_DATE_FIELDS:
    _slug = _doctype.lower().replace(" ", "_")
    globals()[f"get_permission_query_conditions_{_slug}"] = (
        _make_permission_query_conditions(_doctype)
    )

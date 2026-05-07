import frappe
from frappe import qb
from frappe.query_builder import CustomFunction
from frappe.query_builder.custom import ConstantColumn
from frappe.query_builder.functions import Count, IfNull
from frappe.utils import flt

from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
    get_dimensions,
    make_dimension_in_accounting_doctypes,
)

# Note: Only run this script manually if official erpnext script fails or GLE not populated properly.
# Also before running take backup also truncate Payment Ledger Entry table 
# Original patch path erpnext.erpnext.patches.v14_0.migrate_gl_to_payment_ledger

# -------------------------
# Helper Functions
# -------------------------

def create_accounting_dimension_fields():
    dimensions_and_defaults = get_dimensions()
    if dimensions_and_defaults:
        for dimension in dimensions_and_defaults[0]:
            make_dimension_in_accounting_doctypes(dimension, ["Payment Ledger Entry"])


def get_columns():
    columns = [
        "name",
        "creation",
        "modified",
        "modified_by",
        "owner",
        "docstatus",
        "posting_date",
        "account_type",
        "account",
        "party_type",
        "party",
        "voucher_type",
        "voucher_no",
        "against_voucher_type",
        "against_voucher_no",
        "amount",
        "amount_in_account_currency",
        "account_currency",
        "company",
        "cost_center",
        "due_date",
        "finance_book",
    ]

    if frappe.db.has_column("Payment Ledger Entry", "remarks"):
        columns.append("remarks")

    dimensions_and_defaults = get_dimensions()
    if dimensions_and_defaults:
        for dimension in dimensions_and_defaults[0]:
            columns.append(dimension.fieldname)

    return columns


def generate_name_and_calculate_amount(gl_entries, start, receivable_accounts):
    for index, entry in enumerate(gl_entries, 0):
        entry.name = start + index
        if entry.account in receivable_accounts:
            entry.account_type = "Receivable"
            entry.amount = entry.debit - entry.credit
            entry.amount_in_account_currency = entry.debit_in_account_currency - entry.credit_in_account_currency
        else:
            entry.account_type = "Payable"
            entry.amount = entry.credit - entry.debit
            entry.amount_in_account_currency = entry.credit_in_account_currency - entry.debit_in_account_currency


def build_insert_query():
    ple = qb.DocType("Payment Ledger Entry")
    columns = get_columns()
    insert_query = qb.into(ple).columns(tuple(columns))
    return insert_query


def insert_chunk_into_payment_ledger(insert_query, gl_entries):
    if gl_entries:
        columns = get_columns()
        for entry in gl_entries:
            data = tuple(entry[col] for col in columns)
            insert_query = insert_query.insert(data)
        insert_query.run()
        frappe.db.commit()


# -------------------------
# Main Migration Function
# -------------------------

def migrate_gl_to_payment_ledger():
    print("⚙️ Starting Payment Ledger migration...")

    # Ensure accounting dimension fields exist
    create_accounting_dimension_fields()

    gl = qb.DocType("GL Entry")
    account = qb.DocType("Account")
    ifelse = CustomFunction("IF", ["condition", "then", "else"])

    # Fetch Receivable and Payable accounts
    relevant_accounts = (
        qb.from_(account)
        .select(account.name, account.account_type)
        .where((account.account_type == "Receivable") | (account.account_type == "Payable"))
        .orderby(account.name)
        .run(as_dict=True)
    )

    receivable_accounts = [x.name for x in relevant_accounts if x.account_type == "Receivable"]
    accounts = [x.name for x in relevant_accounts]

    # Count unprocessed GL Entries
    unprocessed_count = (
        qb.from_(gl)
        .select(Count(gl.name))
        .where((gl.is_cancelled == 0) & (gl.account.isin(accounts)))
        .run()
    )[0][0]

    if not unprocessed_count:
        print("No eligible GL Entries found. Exiting.")
        return

    print(f"Migrating {unprocessed_count} GL Entries to Payment Ledger…")

    batch_size = 5000
    processed = 0
    last_name = None

    while True:
        where_clause = (gl.account.isin(accounts) & (gl.is_cancelled == 0))
        if last_name:
            where_clause &= gl.name.gt(last_name)

        gl_entries = (
            qb.from_(gl)
            .select(
                gl.star,
                ConstantColumn(1).as_("docstatus"),
                IfNull(ifelse(gl.against_voucher_type == "", None, gl.against_voucher_type), gl.voucher_type).as_("against_voucher_type"),
                IfNull(ifelse(gl.against_voucher == "", None, gl.against_voucher), gl.voucher_no).as_("against_voucher_no"),
            )
            .where(where_clause)
            .orderby(gl.name)
            .limit(batch_size)
            .run(as_dict=True)
        )

        if not gl_entries:
            break

        last_name = gl_entries[-1].name

        # Generate name and calculate amounts
        generate_name_and_calculate_amount(gl_entries, processed, receivable_accounts)

        # Insert into Payment Ledger
        insert_query = build_insert_query()
        insert_chunk_into_payment_ledger(insert_query, gl_entries)

        processed += len(gl_entries)
        percent = flt((processed / unprocessed_count) * 100, 2)
        print(f"{percent}% ({processed}) records processed…")

    print(f"✅ Migration completed. Total records migrated: {processed}")


# from rohit_common.migration_scripts.migrate_gl_to_payment_ledger import migrate_gl_to_payment_ledger
# migrate_gl_to_payment_ledger()
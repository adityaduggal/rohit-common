import frappe
import json
from frappe.utils import flt, nowdate, get_last_day, getdate
from datetime import datetime
from dateutil.relativedelta import relativedelta

try:
    from frappe.query_builder.functions import Sum, Date
except ImportError:
    # Fallback for very old versions (less likely)
    from pypika.functions import Sum
    from pypika.terms import Date

# Import the function from India Compliance
try:
    from india_compliance.gst_india.utils import get_gst_accounts_by_type, get_period
    # We need MONTHS from the utils
    from india_compliance.gst_india.utils import MONTHS
except ImportError:
    print("="*40)
    print("ERROR: Could not import 'india_compliance'.")
    print("Please ensure the 'india_compliance' app is installed.")
    print("="*40)
    raise

GST_START_DATE = "2017-07-01"

def _get_correct_purchase_totals(from_date, to_date):
    """
    Calculates the correct, final INPUT GST totals for a given period
    by summing the data in the (now fixed) Purchase Invoice Item table.
    """
    query = """
        SELECT
            SUM(pii.taxable_value) as total_taxable_value,
            SUM(pii.igst_amount) as total_igst,
            SUM(pii.cgst_amount) as total_cgst,
            SUM(pii.sgst_amount) as total_sgst,
            SUM(pii.cess_amount) as total_cess
        FROM
            `tabPurchase Invoice Item` pii
        JOIN
            `tabPurchase Invoice` pi ON pii.parent = pi.name
        WHERE
            pi.docstatus = 1
            AND pi.posting_date BETWEEN %(from_date)s AND %(to_date)s
    """
    
    result = frappe.db.sql(query, {"from_date": from_date, "to_date": to_date}, as_dict=True)
    
    if not result or not result[0]:
        return {}
        
    summary = result[0]
    return {
        "total_igst_amount": flt(summary.get('total_igst')),
        "total_cgst_amount": flt(summary.get('total_cgst')),
        "total_sgst_amount": flt(summary.get('total_sgst')),
        "total_cess_amount": flt(summary.get('total_cess')),
    }

def _get_gl_input_totals(company, company_gstin, from_date, to_date):
    """
    Gets the *wrong* INPUT totals currently in the General Ledger.
    This is a correct implementation using the query builder functions.
    """
    try:
        # 1. Get the "Input" GST Accounts
        accounts = get_gst_accounts_by_type(company, "Input")
        
        # 2. Query the GL Entry table for those accounts
        gl_entry = frappe.qb.DocType("GL Entry")
        gst_ledger = frappe._dict(
            frappe.qb.from_(gl_entry)
            .select(gl_entry.account, (Sum(gl_entry.debit) - Sum(gl_entry.credit))) # Input tax is a DEBIT
            .where(gl_entry.account.isin(list(accounts.values())))
            .where(gl_entry.company == company)
            .where(Date(gl_entry.posting_date) >= getdate(from_date))
            .where(Date(gl_entry.posting_date) <= getdate(to_date))
            .where(gl_entry.company_gstin == company_gstin)
            .groupby(gl_entry.account)
            .run()
        )
        
        net_input_balance = {
            "total_igst_amount": gst_ledger.get(accounts.get("igst_account"), 0),
            "total_cgst_amount": gst_ledger.get(accounts.get("cgst_account"), 0),
            "total_sgst_amount": gst_ledger.get(accounts.get("sgst_account"), 0),
            "total_cess_amount": gst_ledger.get(accounts.get("cess_account"), 0)
            + gst_ledger.get(accounts.get("cess_non_advol_account"), 0),
        }
        return net_input_balance

    except Exception as e:
        print(f"  Error getting GL totals for period {from_date}: {e}")
        return {}

def create_adjustment_je(company, company_gstin, posting_date, diff_totals, expense_account, gst_accounts, dry_run=True):
    """
    Creates and submits the adjustment Journal Entry for Input Tax.
    """
    total_adjustment = sum(diff_totals.values())
    
    if abs(total_adjustment) < 0.01:
        print(f"  Skipping {posting_date}: No adjustment needed.")
        return None

    default_cost_center = frappe.db.get_value("Company", company, "cost_center")
    if not default_cost_center:
        print(f"  WARNING: No default Cost Center found for company {company}. JEs might fail if Cost Center is mandatory.")
        default_cost_center = "Main - " + frappe.db.get_value("Company", company, "abbr")


    je_doc = {
        "doctype": "Journal Entry",
        "company": company,
        "company_gstin": company_gstin,
        "posting_date": posting_date,
        "voucher_type": "Journal Entry",
        "user_remark": f"Automated GST Input Tax adjustment for migrated invoices, period {posting_date.strftime('%b-%Y')}",
        "accounts": []
    }
    
    # 1. Debit the individual tax accounts
    if diff_totals["total_igst_amount"] > 0.01:
        je_doc["accounts"].append({
            "account": gst_accounts["igst_account"],
            "debit_in_account_currency": flt(diff_totals["total_igst_amount"], 2),
            "credit_in_account_currency": 0,
            "cost_center": default_cost_center
        })

    if diff_totals["total_cgst_amount"] > 0.01:
        je_doc["accounts"].append({
            "account": gst_accounts["cgst_account"],
            "debit_in_account_currency": flt(diff_totals["total_cgst_amount"], 2),
            "credit_in_account_currency": 0,
            "cost_center": default_cost_center
        })

    if diff_totals["total_sgst_amount"] > 0.01:
        je_doc["accounts"].append({
            "account": gst_accounts["sgst_account"],
            "debit_in_account_currency": flt(diff_totals["total_sgst_amount"], 2),
            "credit_in_account_currency": 0,
            "cost_center": default_cost_center
        })

    if diff_totals["total_cess_amount"] > 0.01:
        cess_acct = gst_accounts.get("cess_account") or gst_accounts.get("cess_non_advol_account")
        if not cess_acct:
            print(f"  WARNING: No CESS account found in GST Accounts. Skipping CESS amount {diff_totals['total_cess_amount']}")
        else:
            je_doc["accounts"].append({
                "account": cess_acct,
                "debit_in_account_currency": flt(diff_totals["total_cess_amount"], 2),
                "credit_in_account_currency": 0,
                "cost_center": default_cost_center
            })

    # 2. Credit the main Expense account
    je_doc["accounts"].append({
        "account": expense_account,
        "debit_in_account_currency": 0,
        "credit_in_account_currency": flt(total_adjustment, 2),
        "cost_center": default_cost_center
    })
    
    print(f"  Period {posting_date.strftime('%b-%Y')}: Total Input Tax Adjustment: {flt(total_adjustment, 2)}")
    
    if dry_run:
        print(f"  [DRY RUN] Would create JE with {len(je_doc['accounts'])} lines.")
        return None

    try:
        je = frappe.get_doc(je_doc)
        je.insert()
        je.submit()
        print(f"  SUCCESS: Created and Submitted JE {je.name} for {posting_date.strftime('%b-%Y')}")
        return je.name
    except Exception as e:
        print(f"  ERROR creating JE for {posting_date.strftime('%b-%Y')}: {e}")
        frappe.log_error(title="GST Input Tax Adjustment JE Failed")
        return None


def execute(company, company_gstin, dry_run=True, default_expense_account=None):
    """
    Main execution function.
    """
    dry_run = bool(dry_run)
    print(f"*** STARTING GST INPUT TAX ADJUSTMENT JOURNAL ENTRY CREATION (V2 - Rerunnable) ***")
    print(f"*** {'DRY RUN' if dry_run else 'APPLYING CHANGES'} ***")
    print(f"*** Company: {company} | GSTIN: {company_gstin} ***")
    
    # --- Find Accounts ---
    try:
        gst_accounts = get_gst_accounts_by_type(company, "Input")
        if not gst_accounts.get("igst_account") or not gst_accounts.get("cgst_account"):
            print(f"ERROR: Could not find GST Input accounts for Company '{company}'. Check your Chart of Accounts.")
            return
    except Exception as e:
        print(f"ERROR: Failed to get GST accounts. Is 'india_compliance' app installed correctly? {e}")
        return

    if default_expense_account:
        expense_account = default_expense_account
    else:
        expense_account = None
        expense_account_query = f"""
            SELECT expense_account 
            FROM `tabPurchase Invoice Item` pii
            JOIN `tabPurchase Invoice` pi ON pii.parent = pi.name
            WHERE pi.posting_date >= '{GST_START_DATE}'
            AND pi.company = %(company)s
            AND pii.expense_account IS NOT NULL
            AND pii.expense_account != ''
            GROUP BY expense_account 
            ORDER BY COUNT(*) DESC 
            LIMIT 1
        """
        expense_account_result = frappe.db.sql(expense_account_query, {"company": company})
        if expense_account_result and expense_account_result[0]:
            expense_account = expense_account_result[0][0]
    
    if not expense_account:
        print(f"ERROR: Could not guess 'default_expense_account'. Please pass it as an argument.")
        print("Example: --kwargs \"{'company': 'My Company', ..., 'default_expense_account': 'Expenses Included In Valuation'}\"")
        return

    print(f"Using fallback Expense Account: {expense_account}")
    print(f"Using Tax Accounts: IGST:{gst_accounts.get('igst_account')}, CGST:{gst_accounts.get('cgst_account')}, ...")
    print("---")
    
    # --- Loop through all periods ---
    start_date = datetime.strptime(GST_START_DATE, "%Y-%m-%d").date()
    end_date = getdate(nowdate())
    
    current_date = start_date
    
    while current_date <= end_date:
        month_name = current_date.strftime("%B")
        year = current_date.strftime("%Y")
        period_start = current_date
        period_end = get_last_day(current_date)
        
        if current_date.year == end_date.year and current_date.month == end_date.month:
            print(f"Skipping current month ({month_name} {year}) as it is not yet complete.")
            break
        
        print(f"Processing Period: {month_name} {year} ({period_start} to {period_end})")
        
        remark_search = f"Automated GST Input Tax adjustment for migrated invoices, period {period_end.strftime('%b-%Y')}"
        je_exists = frappe.db.exists("Journal Entry", {
            "posting_date": period_end,
            "user_remark": ["like", f"%{remark_search}%"],
            "docstatus": 1
        })
        
        if je_exists:
            print(f"  Skipping {month_name} {year}: Adjustment JE {je_exists} already exists.")
            current_date = current_date + relativedelta(months=1)
            continue

        correct_totals = _get_correct_purchase_totals(period_start, period_end)
        
        wrong_totals = _get_gl_input_totals(company, company_gstin, period_start, period_end)
        
        if not correct_totals and (not wrong_totals or sum(wrong_totals.values()) == 0):
            print("  No data found in Items or GL. Skipping.")
            current_date = current_date + relativedelta(months=1)
            continue
            
        diff_totals = {
            "total_igst_amount": flt(correct_totals.get("total_igst_amount")) - flt(wrong_totals.get("total_igst_amount")),
            "total_cgst_amount": flt(correct_totals.get("total_cgst_amount")) - flt(wrong_totals.get("total_cgst_amount")),
            "total_sgst_amount": flt(correct_totals.get("total_sgst_amount")) - flt(wrong_totals.get("total_sgst_amount")),
            "total_cess_amount": flt(correct_totals.get("total_cess_amount")) - flt(wrong_totals.get("total_cess_amount")),
        }
        
        create_adjustment_je(
            company=company,
            company_gstin=company_gstin,
            posting_date=period_end,
            diff_totals=diff_totals,
            expense_account=expense_account,
            gst_accounts=gst_accounts,
            dry_run=dry_run
        )
        
        current_date = current_date + relativedelta(months=1)
        
    print("\n--- SCRIPT FINISHED ---")


# bench --site development.localhost execute rohit_common.migration_scripts.create_purchase_gst_adjustment_jes.execute \
#   --kwargs "{ \
#     'company': 'Rohit Industries Group Private Ltd', \
#     'company_gstin': '06AAACR1567J1ZC', \
#     'dry_run': True \
#   }"

# bench --site development.localhost execute rohit_common.migration_scripts.create_purchase_gst_adjustment_jes.execute \
#   --kwargs "{ \
#     'company': 'Rohit Industries Group Private Ltd', \
#     'company_gstin': '06AAACR1567J1ZC', \
#     'dry_run': False \
#   }"
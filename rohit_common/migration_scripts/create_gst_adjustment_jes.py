# rohit_common/utils/create_gst_adjustment_jes.py
import frappe
import json
from frappe.utils import flt, nowdate, get_last_day, getdate 
from datetime import datetime
from dateutil.relativedelta import relativedelta

# Import the function from India Compliance to read GL totals
try:
    from india_compliance.gst_india.doctype.gstr_1.gstr_1 import get_net_gst_liability
    from india_compliance.gst_india.utils import get_gst_accounts_by_type
except ImportError:
    print("="*40)
    print("ERROR: Could not import 'india_compliance'.")
    print("Please ensure the 'india_compliance' app is installed.")
    print("="*40)
    raise

GST_START_DATE = "2017-07-01"

def _get_correct_totals(from_date, to_date):
    """
    Calculates the correct, final GST totals for a given period
    by summing the data in the (now fixed) Sales Invoice Item table.
    """
    query = """
        SELECT
            SUM(sii.taxable_value) as total_taxable_value,
            SUM(sii.igst_amount) as total_igst,
            SUM(sii.cgst_amount) as total_cgst,
            SUM(sii.sgst_amount) as total_sgst,
            SUM(sii.cess_amount) as total_cess
        FROM
            `tabSales Invoice Item` sii
        JOIN
            `tabSales Invoice` si ON sii.parent = si.name
        WHERE
            si.docstatus = 1
            AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s
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

def _get_gl_totals(company, company_gstin, month, year, filing_preference="Monthly"):
    """
    Gets the *wrong* totals currently in the General Ledger.
    This uses the exact same function as the GSTR-1 report.
    """
    try:
        # Note: This function reads from `tabGL Entry`
        totals = get_net_gst_liability(
            company=company,
            company_gstin=company_gstin,
            month_or_quarter=month,
            year=year,
            filing_preference=filing_preference
        )
        return totals
    except Exception as e:
        print(f"  Error getting GL totals for {month}-{year}: {e}")
        return {}

def create_adjustment_je(company, company_gstin, posting_date, diff_totals, sales_account, gst_accounts, dry_run=True):
    """
    Creates and submits the adjustment Journal Entry.
    """
    total_adjustment = sum(diff_totals.values())
    
    if abs(total_adjustment) < 0.01:
        print(f"  Skipping {posting_date}: No adjustment needed.")
        return None

    # Get default cost center
    default_cost_center = frappe.db.get_value("Company", company, "cost_center")
    if not default_cost_center:
        print(f"  WARNING: No default Cost Center found for company {company}. JEs might fail if Cost Center is mandatory.")
        # Fallback just in case
        default_cost_center = "Main - " + frappe.db.get_value("Company", company, "abbr")


    je_doc = {
        "doctype": "Journal Entry",
        "company": company,
        "company_gstin": company_gstin,
        "posting_date": posting_date,
        "voucher_type": "Journal Entry",
        "user_remark": f"Automated GST adjustment for migrated invoices, period {posting_date.strftime('%b-%Y')}",
        "accounts": []
    }
    
    # 1. Debit the Sales account
    je_doc["accounts"].append({
        "account": sales_account,
        "debit_in_account_currency": flt(total_adjustment, 2),
        "credit_in_account_currency": 0,
        "cost_center": default_cost_center
    })
    
    # 2. Credit the individual tax accounts
    if diff_totals["total_igst_amount"] > 0.01:
        je_doc["accounts"].append({
            "account": gst_accounts["igst_account"],
            "debit_in_account_currency": 0,
            "credit_in_account_currency": flt(diff_totals["total_igst_amount"], 2),
            "cost_center": default_cost_center
        })

    if diff_totals["total_cgst_amount"] > 0.01:
        je_doc["accounts"].append({
            "account": gst_accounts["cgst_account"],
            "debit_in_account_currency": 0,
            "credit_in_account_currency": flt(diff_totals["total_cgst_amount"], 2),
            "cost_center": default_cost_center
        })

    if diff_totals["total_sgst_amount"] > 0.01:
        je_doc["accounts"].append({
            "account": gst_accounts["sgst_account"],
            "debit_in_account_currency": 0,
            "credit_in_account_currency": flt(diff_totals["total_sgst_amount"], 2),
            "cost_center": default_cost_center
        })

    if diff_totals["total_cess_amount"] > 0.01:
        cess_acct = gst_accounts.get("cess_account") or gst_accounts.get("cess_non_advol_account")
        if not cess_acct:
            print(f"  WARNING: No CESS account found in GST Accounts. Skipping CESS amount {diff_totals['total_cess_amount']}")
        else:
            je_doc["accounts"].append({
                "account": cess_acct,
                "debit_in_account_currency": 0,
                "credit_in_account_currency": flt(diff_totals["total_cess_amount"], 2),
                "cost_center": default_cost_center
            })

    print(f"  Period {posting_date.strftime('%b-%Y')}: Total Adjustment: {flt(total_adjustment, 2)}")
    
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
        frappe.log_error(title="GST Adjustment JE Failed")
        return None


def execute(company, company_gstin, dry_run=True, default_sales_account=None):
    """
    Main execution function.
    
    :param company: Your Company name, e.g., "Rohit Industries Group Private Ltd"
    :param company_gstin: Your Company GSTIN, e.g., "06AAACR1567J1ZC"
    :param dry_run: If True, no JEs will be created.
    :param default_sales_account: (Optional) Specify your main Income/Sales account.
                                  If None, the script will try to guess it.
    """
    dry_run = bool(dry_run)
    print(f"*** STARTING GST ADJUSTMENT JOURNAL ENTRY CREATION (V3) ***")
    print(f"*** {'DRY RUN' if dry_run else 'APPLYING CHANGES'} ***")
    print(f"*** Company: {company} | GSTIN: {company_gstin} ***")
    
    # --- Find Accounts ---
    try:
        gst_accounts = get_gst_accounts_by_type(company, "Output")
        if not gst_accounts.get("igst_account") or not gst_accounts.get("cgst_account"):
            print(f"ERROR: Could not find GST Output accounts for Company '{company}'. Check your Chart of Accounts.")
            return
    except Exception as e:
        print(f"ERROR: Failed to get GST accounts. Is 'india_compliance' app installed correctly? {e}")
        return

    if default_sales_account:
        sales_account = default_sales_account
    else:
        sales_account = None
        sales_account_query = f"""
            SELECT income_account 
            FROM `tabSales Invoice Item` sii
            JOIN `tabSales Invoice` si ON sii.parent = si.name
            WHERE si.posting_date >= '{GST_START_DATE}'
            AND si.company = %(company)s
            AND sii.income_account IS NOT NULL
            AND sii.income_account != ''
            GROUP BY income_account 
            ORDER BY COUNT(*) DESC 
            LIMIT 1
        """
        sales_account_result = frappe.db.sql(sales_account_query, {"company": company})
        if sales_account_result and sales_account_result[0]:
            sales_account = sales_account_result[0][0]
    
    if not sales_account:
        print(f"ERROR: Could not guess 'default_sales_account'. Please pass it as an argument.")
        print("Example: --kwargs \"{'company': 'My Company', ..., 'default_sales_account': 'Sales - RIGB'}\"")
        return

    print(f"Using Income Account: {sales_account}")
    print(f"Using Tax Accounts: IGST:{gst_accounts.get('igst_account')}, CGST:{gst_accounts.get('cgst_account')}, ...")
    print("---")
    
    # --- Loop through all periods ---
    start_date = datetime.strptime(GST_START_DATE, "%Y-%m-%d").date()
    
    end_date = getdate(nowdate()) # Convert string from nowdate() to a date object
    
    current_date = start_date
    
    while current_date <= end_date:
        month_name = current_date.strftime("%B")
        year = current_date.strftime("%Y")
        period_start = current_date
        period_end = get_last_day(current_date)
        
        # Don't process the current, incomplete month. Stop at the beginning of this month.
        if current_date.year == end_date.year and current_date.month == end_date.month:
            print(f"Skipping current month ({month_name} {year}) as it is not yet complete.")
            break
        
        print(f"Processing Period: {month_name} {year} ({period_start} to {period_end})")
        
        # 1. Get Correct totals from fixed Sales Invoice Items
        correct_totals = _get_correct_totals(period_start, period_end)
        
        # 2. Get Wrong totals from General Ledger
        wrong_totals = _get_gl_totals(company, company_gstin, month_name, year)
        
        if not correct_totals and (not wrong_totals or sum(wrong_totals.values()) == 0):
            print("  No data found in Items or GL. Skipping.")
            current_date = current_date + relativedelta(months=1)
            continue
            
        # 3. Calculate the difference
        diff_totals = {
            "total_igst_amount": flt(correct_totals.get("total_igst_amount")) - flt(wrong_totals.get("total_igst_amount")),
            "total_cgst_amount": flt(correct_totals.get("total_cgst_amount")) - flt(wrong_totals.get("total_cgst_amount")),
            "total_sgst_amount": flt(correct_totals.get("total_sgst_amount")) - flt(wrong_totals.get("total_sgst_amount")),
            "total_cess_amount": flt(correct_totals.get("total_cess_amount")) - flt(wrong_totals.get("total_cess_amount")),
        }
        
        # 4. Create the JE
        create_adjustment_je(
            company=company,
            company_gstin=company_gstin,
            posting_date=period_end, # Post on the last day of the month
            diff_totals=diff_totals,
            sales_account=sales_account,
            gst_accounts=gst_accounts,
            dry_run=dry_run
        )
        
        # Move to the next month
        current_date = current_date + relativedelta(months=1)
        
    print("\n--- SCRIPT FINISHED ---")

# bench --site development.localhost execute rohit_common.migration_scripts.create_gst_adjustment_jes.execute \
#   --kwargs "{ \
#     'company': 'Rohit Industries Group Private Ltd', \
#     'company_gstin': '06AAACR1567J1ZC', \
#     'dry_run': True \
#   }"


# bench --site development.localhost execute rohit_common.migration_scripts.create_gst_adjustment_jes.execute \
#   --kwargs "{ \
#     'company': 'Rohit Industries Group Private Ltd', \
#     'company_gstin': '06AAACR1567J1ZC', \
#     'dry_run': False \
#   }"

# before running enable all fiscal year and acc_frozen_upto from account settings
# manually cancel all period closing voucher and after completing the script submit them again
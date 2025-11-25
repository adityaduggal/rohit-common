# -*- coding: utf-8 -*-

import frappe

# avoid importing erpnext unless tables exist
try:
    import erpnext
except Exception:
    erpnext = None

def execute():
    # Don't run heavy ORM logic if the DB/schema isn't ready
    run_unwanted_patches()
    add_default_company_fy()


def table_exists(table_name: str) -> bool:
    """
    Return True if a physical SQL table `table_name` exists.
    `table_name` should be the exact table name e.g. 'tabFiscal Year'.
    """
    try:
        # most frappe DB backends support this helper
        if hasattr(frappe.db, "table_exists"):
            return frappe.db.table_exists(table_name)
    except Exception:
        # fall through to basic SQL check
        pass

    try:
        res = frappe.db.sql("SHOW TABLES LIKE %s", (table_name,))
        return bool(res)
    except Exception:
        return False


def run_unwanted_patches():
    # keep existing behavior (import inside function to avoid imports at module load)
    try:
        from rohit_common.patches.run_unwanted_patches import run_unwanted_patches as _rup
        _rup()
    except Exception as e:
        # If patch runner can't be imported/run at this stage, log and continue.
        print("run_unwanted_patches() skipped (not available at this stage):", e)


def add_default_company_fy():
    # guard: ensure SQL tables exist before calling any ORM that triggers permission/meta resolution
    if not table_exists("tabFiscal Year"):
        print("Skipping add_default_company_fy(): table `tabFiscal Year` is not present yet.")
        return

    # If you call erpnext.get_default_company(), ensure Company table exists
    if erpnext is None or not table_exists("tabCompany"):
        print("Skipping setting default company for Fiscal Year: Company table / erpnext not available yet.")
        return

    # safe to query the fiscal years directly via SQL (avoids permission checks)
    try:
        rows = frappe.db.sql(
            "SELECT `name` FROM `tabFiscal Year` ORDER BY `year_start_date` ASC",
            as_dict=True,
        )
    except Exception as e:
        print("Failed to read `tabFiscal Year` via SQL; skipping. Error:", e)
        return

    def_comp = None
    try:
        # call erpnext helper now that erpnext import succeeded and Company table exists
        def_comp = erpnext.get_default_company()
    except Exception as e:
        print("erpnext.get_default_company() failed; skipping adding default company to Fiscal Year. Error:", e)
        return

    for r in rows:
        fy_name = r.get("name")
        if not fy_name:
            continue

        # check if there is already a Fiscal Year Company link — use a direct SQL check
        try:
            existing = frappe.db.sql(
                """
                SELECT 1 FROM `tabFiscal Year Company`
                WHERE parent=%s LIMIT 1
                """,
                (fy_name,),
            )
        except Exception as e:
            print(f"Could not query Fiscal Year Company for {fy_name}; skipping. Error:", e)
            continue

        if existing:
            # already has a company -> nothing to do
            continue

        try:
            fydoc = frappe.get_doc("Fiscal Year", fy_name)
            fydoc.append("companies", {"company": def_comp})
            fydoc.save()
            print(f"Set default company {def_comp} for Fiscal Year {fy_name}")
        except Exception as e:
            print(f"Failed to append company for Fiscal Year {fy_name}: {e}")

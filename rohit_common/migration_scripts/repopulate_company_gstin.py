import frappe

def repopulate_sales_invoice_company_gstin(dry_run=True, batch_size=200, limit=None):
    """
    Populate Sales Invoice.company_gstin from Company (common GSTIN fields).
    - dry_run=True : only prints what would be changed
    - batch_size : number of updates before commit
    - limit : optional integer - limit number of invoices processed (for testing)
    Returns a summary dict.
    """
    frappe.flags.in_migrate = True

    possible_company_gstin_fields = ["company_gstin", "gstin", "gstin_number", "tax_id", "tax_id_number"]

    # build company -> gstin mapping
    company_gstin_map = {}
    for c in frappe.get_all("Company", fields=["name"]):
        cname = c.get("name")
        try:
            comp_doc = frappe.get_doc("Company", cname)
        except Exception:
            continue
        gst = None
        for f in possible_company_gstin_fields:
            if hasattr(comp_doc, f):
                val = comp_doc.get(f)
                if val:
                    gst = val.strip()
                    break
        if gst:
            company_gstin_map[cname] = gst

    # fetch invoices where company_gstin is empty or null
    # NOTE: use limit_page_length only if limit not given
    kwargs = {
        "filters": {"company_gstin": ["in", ["", None]]},
        "fields": ["name", "company", "posting_date"],
    }
    if limit:
        kwargs["limit_page_length"] = limit
    else:
        kwargs["limit_page_length"] = 100000

    invoices = frappe.get_all("Sales Invoice", **kwargs)

    # fallback to SQL if get_all returned nothing (covers schema mismatches)
    if not invoices:
        limit_clause = "LIMIT %s" % int(limit) if limit else ""
        invoices = frappe.db.sql(
            f"""
            SELECT name, company, posting_date
            FROM `tabSales Invoice`
            WHERE IFNULL(company_gstin, '') = ''
            {limit_clause}
            """,
            as_dict=True,
        )

    total = len(invoices)
    print("Found %d Sales Invoice(s) with empty company_gstin." % total)
    if total == 0:
        return {"total_found": 0, "updated": 0, "skipped_no_company": 0, "skipped_no_gstin": 0, "errors": []}

    updated = 0
    skipped_no_company = 0
    skipped_no_gstin = 0
    errors = []
    counter = 0

    for inv in invoices:
        counter += 1
        name = inv.get("name")
        company = inv.get("company")
        posting_date = inv.get("posting_date")

        if not company:
            skipped_no_company += 1
            print(f"[{counter}/{total}] SKIP {name} — no company set.")
            continue

        gst_value = company_gstin_map.get(company)
        if not gst_value:
            # try reading company doc live
            try:
                comp_doc = frappe.get_doc("Company", company)
                for f in possible_company_gstin_fields:
                    if hasattr(comp_doc, f):
                        val = comp_doc.get(f)
                        if val:
                            gst_value = val.strip()
                            break
            except Exception as e:
                errors.append((name, f"read company error: {e}"))
                print(f"[{counter}/{total}] ERROR reading Company for {name}: {e}")
                continue

        if not gst_value:
            skipped_no_gstin += 1
            print(f"[{counter}/{total}] SKIP {name} — company '{company}' has no GSTIN.")
            continue

        print(f"[{counter}/{total}] Invoice {name}: set company_gstin -> {gst_value} (company: {company}, posting_date: {posting_date})")

        if not dry_run:
            try:
                frappe.db.set_value("Sales Invoice", name, "company_gstin", gst_value, update_modified=True)
                updated += 1
            except Exception as e:
                errors.append((name, f"update error: {e}"))
                print(f"  ERROR updating {name}: {e}")

            if updated and (updated % batch_size == 0):
                frappe.db.commit()
                print("  Committed batch up to %d updates." % updated)

    if not dry_run:
        frappe.db.commit()
        print("Final commit done.")

    print("Done. Summary:")
    print(f"  Total invoices found: {total}")
    print(f"  Updated: {updated}")
    print(f"  Skipped (no company set): {skipped_no_company}")
    print(f"  Skipped (company has no GSTIN): {skipped_no_gstin}")
    print(f"  Errors: {len(errors)}")

    return {
        "total_found": total,
        "updated": updated,
        "skipped_no_company": skipped_no_company,
        "skipped_no_gstin": skipped_no_gstin,
        "errors": errors,
    }

# bench execute entrypoint
def execute(dry_run=True, batch_size=200, limit=None):
    # bench execute passes JSON-like values; ensure types are correct
    dry_run = bool(dry_run)
    batch_size = int(batch_size) if batch_size else 200
    limit = int(limit) if limit else None
    return repopulate_sales_invoice_company_gstin(dry_run=dry_run, batch_size=batch_size, limit=limit)

# dry run - prints actions, does not write
# bench --site development.localhost execute rohit_common.migration_scripts.repopulate_company_gstin.execute --kwargs "{'dry_run': True, 'limit': 100}"

# when happy, perform actual update (no limit):
# bench --site development.localhost execute rohit_common.migration_scripts.repopulate_company_gstin.execute --kwargs "{'dry_run': False, 'batch_size': 200}"

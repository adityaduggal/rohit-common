import frappe

def repopulate_gl_entry_company_gstin(dry_run=True, batch_size=1000, limit=None):
    """
    Populate GL Entry.company_gstin from Company (common GSTIN fields).
    - dry_run=True : only prints what would be changed
    - batch_size : number of updates before commit
    - limit : optional integer - limit number of entries processed (for testing)
    Returns a summary dict.
    """
    # Important for GL Entries to bypass some immutable checks during migration
    frappe.flags.in_migrate = True

    possible_company_gstin_fields = ["company_gstin", "gstin", "gstin_number", "tax_id", "tax_id_number"]

    # 1. Build company -> gstin mapping
    print("Building Company GSTIN Map...")
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

    # 2. Fetch GL Entries where company_gstin is empty or null
    print("Fetching GL Entries with missing GSTIN...")
    
    limit_clause = f"LIMIT {int(limit)}" if limit else ""
    
    # Using SQL directly for fetching is faster for GL Entry due to table size
    gl_entries = frappe.db.sql(
        f"""
        SELECT name, company, posting_date
        FROM `tabGL Entry`
        WHERE IFNULL(company_gstin, '') = ''
        {limit_clause}
        """,
        as_dict=True,
    )

    total = len(gl_entries)
    print(f"Found {total} GL Entry(s) with empty company_gstin.")
    
    if total == 0:
        return {"total_found": 0, "updated": 0, "skipped": 0, "errors": []}

    updated = 0
    skipped = 0
    errors = []
    counter = 0

    for gle in gl_entries:
        counter += 1
        name = gle.get("name")
        company = gle.get("company")
        posting_date = gle.get("posting_date")

        if not company:
            skipped += 1
            continue

        # Get GSTIN from map
        gst_value = company_gstin_map.get(company)

        # If not in map, try last ditch fetch (rarely needed if map built correctly)
        if not gst_value:
            skipped += 1
            print(f"[{counter}/{total}] SKIP {name} — Company '{company}' has no GSTIN found.")
            continue

        if dry_run:
            # Print only every 100th line to avoid spamming console on huge GL tables
            if counter % 100 == 0 or counter < 20: 
                print(f"[{counter}/{total}] Would update {name}: {company} -> {gst_value}")
        else:
            try:
                # update_modified=False preserves the original modification date of the ledger entry
                frappe.db.set_value("GL Entry", name, "company_gstin", gst_value, update_modified=False)
                updated += 1
            except Exception as e:
                errors.append((name, str(e)))
                print(f"  ERROR updating {name}: {e}")

            if updated and (updated % batch_size == 0):
                frappe.db.commit()
                print(f"  Committed batch up to {updated} updates...")

    if not dry_run:
        frappe.db.commit()
        print("Final commit done.")

    print("Done. Summary:")
    print(f"  Total found: {total}")
    print(f"  Updated: {updated}")
    print(f"  Skipped: {skipped}")
    print(f"  Errors: {len(errors)}")

    return {
        "total_found": total,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
    }

# bench execute entrypoint
def execute(dry_run=True, batch_size=1000, limit=None):
    dry_run = bool(dry_run)
    batch_size = int(batch_size) if batch_size else 1000
    limit = int(limit) if limit else None
    return repopulate_gl_entry_company_gstin(dry_run=dry_run, batch_size=batch_size, limit=limit)

# Command to run (Dry Run):
# bench --site [your-site] execute path.to.script.execute --kwargs "{'dry_run': True, 'limit': 100}"

# Command to run (Actual):
# bench --site [your-site] execute path.to.script.execute --kwargs "{'dry_run': False, 'batch_size': 2000}"

# bench --site development.localhost execute rohit_common.migration_scripts.gl_entry_update.execute --kwargs "{'dry_run': False, 'batch_size': 2000}"
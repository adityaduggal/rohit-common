import frappe

def repopulate_journal_entry_company_gstin(
    dry_run=True, batch_size=1000, limit=None
):
    """
    Populate Journal Entry.company_gstin from Company master.
    Only fills missing GSTINs.
    """

    frappe.flags.in_migrate = True

    possible_company_gstin_fields = [
        "company_gstin", "gstin", "gstin_number", "tax_id", "tax_id_number"
    ]

    print("Building Company GSTIN Map...")
    company_gstin_map = {}

    for c in frappe.get_all("Company", fields=["name"]):
        try:
            comp = frappe.get_doc("Company", c.name)
        except Exception:
            continue

        gst = None
        for f in possible_company_gstin_fields:
            if hasattr(comp, f):
                val = comp.get(f)
                if val:
                    gst = val.strip()
                    break

        if gst:
            company_gstin_map[c.name] = gst

    limit_clause = f"LIMIT {int(limit)}" if limit else ""

    print("Fetching Journal Entries with missing GSTIN...")

    jes = frappe.db.sql(
        f"""
        SELECT name, company, posting_date
        FROM `tabJournal Entry`
        WHERE docstatus = 1
          AND IFNULL(company_gstin, '') = ''
          AND company IS NOT NULL
        {limit_clause}
        """,
        as_dict=True,
    )

    total = len(jes)
    print(f"Found {total} Journal Entry(s)")

    updated = skipped = 0
    errors = []

    for idx, je in enumerate(jes, start=1):
        company = je.company
        gstin = company_gstin_map.get(company)

        if not gstin:
            skipped += 1
            continue

        if dry_run:
            if idx <= 20 or idx % 100 == 0:
                print(f"[{idx}/{total}] Would update {je.name} → {gstin}")
        else:
            try:
                frappe.db.set_value(
                    "Journal Entry",
                    je.name,
                    "company_gstin",
                    gstin,
                    update_modified=False,
                )
                updated += 1
            except Exception as e:
                errors.append((je.name, str(e)))

            if updated and updated % batch_size == 0:
                frappe.db.commit()
                print(f"Committed {updated} updates")

    if not dry_run:
        frappe.db.commit()
        print("Final commit done")

    print("Summary")
    print("Total:", total)
    print("Updated:", updated)
    print("Skipped:", skipped)
    print("Errors:", len(errors))

    return {
        "total": total,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
    }


def execute(dry_run=True, batch_size=1000, limit=None):
    return repopulate_journal_entry_company_gstin(
        dry_run=bool(dry_run),
        batch_size=int(batch_size or 1000),
        limit=int(limit) if limit else None,
    )

# bench --site development.localhost \
#   execute rohit_common.migration_scripts.je_company_gstin.execute \
#   --kwargs "{'dry_run': True, 'limit': 50}"

# bench --site development.localhost \
#   execute rohit_common.migration_scripts.je_company_gstin.execute \
#   --kwargs "{'dry_run': False, 'batch_size': 2000}"

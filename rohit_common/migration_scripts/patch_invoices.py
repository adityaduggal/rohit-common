import frappe

def run_patch(dry_run=True):
    """
    Patches old Sales Invoices with missing gst_category and place_of_supply
    after migrating from v12 to v15.
    
    V5 Logic:
    - Uses correct category names ("Registered Regular", "Unregistered").
    - Checks both `customer_gstin` and `billing_address_gstin` to find registered customers.
    - Re-formats `place_of_supply` from "State Name" to "Code-State Name" using the built-in map.
    - Falls back to checking the linked Address if data is missing.
    """
    
    # State mapping you provided from the constants file
    STATE_NUMBERS = {
        "Andaman and Nicobar Islands": "35", "Andhra Pradesh": "37", "Arunachal Pradesh": "12",
        "Assam": "18", "Bihar": "10", "Chandigarh": "04", "Chhattisgarh": "22",
        "Dadra and Nagar Haveli and Daman and Diu": "26", "Delhi": "07", "Goa": "30",
        "Gujarat": "24", "Haryana": "06", "Himachal Pradesh": "02", "Jammu and Kashmir": "01",
        "Jharkhand": "20", "Karnataka": "29", "Kerala": "32", "Ladakh": "38",
        "Lakshadweep Islands": "31", "Madhya Pradesh": "23", "Maharashtra": "27", "Manipur": "14",
        "Meghalaya": "17", "Mizoram": "15", "Nagaland": "13", "Odisha": "21",
        "Other Countries": "96", "Other Territory": "97", "Puducherry": "34", "Punjab": "03",
        "Rajasthan": "08", "Sikkim": "11", "Tamil Nadu": "33", "Telangana": "36",
        "Tripura": "16", "Uttar Pradesh": "09", "Uttarakhand": "05", "West Bengal": "19",
    }
    
    frappe.db.auto_commit_on_many_writes = True
    post_gst_start_date = "2017-07-01"

    print("--- Starting Patch for GST Fields (V5 Logic) ---")
    if dry_run:
        print("*** DRY RUN MODE: No changes will be saved. ***")
    
    print("Finding invoices to patch...")
    
    # We query for invoices that have a blank category OR a place_of_supply
    # that does NOT contain a hyphen (e.g., "Tamil Nadu" instead of "33-Tamil Nadu")
    invoices_to_patch = frappe.db.sql(f"""
        SELECT 
            name, customer_gstin, billing_address_gstin, 
            customer_address, shipping_address_name, place_of_supply, gst_category
        FROM 
            `tabSales Invoice`
        WHERE 
            docstatus = 1 
            AND posting_date >= '{post_gst_start_date}'
            AND (
                IFNULL(gst_category, '') = ''
                OR IFNULL(place_of_supply, '') = ''
                OR place_of_supply NOT LIKE '%-%'
            )
    """, as_dict=True)

    total_invoices = len(invoices_to_patch)
    if not total_invoices:
        print("No invoices found that need patching. Exiting.")
        return

    print(f"Found {total_invoices} submitted invoices to patch...")
    
    updated_count = 0
    failed_count = 0
    processed_count = 0

    for i, inv in enumerate(invoices_to_patch):
        processed_count += 1
        doc_needs_update = False
        update_data = {}
        log_msgs = []

        try:
            # 1. Logic for GST Category
            if not inv.gst_category:
                customer_has_gstin = inv.customer_gstin or inv.billing_address_gstin
                
                if customer_has_gstin:
                    update_data["gst_category"] = "Registered Regular"
                    log_msgs.append("set gst_category=Registered Regular")
                else:
                    update_data["gst_category"] = "Unregistered"
                    log_msgs.append("set gst_category=Unregistered")
                doc_needs_update = True

            # 2. Logic for Place of Supply
            current_pos = inv.place_of_supply
            pos_is_correct_format = current_pos and "-" in current_pos

            if not pos_is_correct_format:
                new_pos_value = None
                
                # Try 1: Re-format the existing value (e.g., "Tamil Nadu")
                if current_pos:
                    state_name = current_pos.strip()
                    state_code = STATE_NUMBERS.get(state_name)
                    if state_code:
                        new_pos_value = f"{state_code}-{state_name}"
                        log_msgs.append(f"re-formatted place_of_supply to {new_pos_value}")

                # Try 2: If Try 1 failed (blank field or bad state name), get from Address
                if not new_pos_value:
                    address_name = inv.customer_address or inv.shipping_address_name
                    if address_name:
                        gst_state = frappe.db.get_value("Address", address_name, "gst_state")
                        if gst_state and "-" in gst_state: # Ensure address value is valid
                            new_pos_value = gst_state
                            log_msgs.append(f"set place_of_supply from Address {address_name}")
                
                # Now, update if we found a value
                if new_pos_value:
                    update_data["place_of_supply"] = new_pos_value
                    doc_needs_update = True
                elif not current_pos:
                     log_msgs.append("SKIP place_of_supply: Field is blank and linked Address has no data.")
                else:
                     log_msgs.append(f"SKIP place_of_supply: Unknown state name '{current_pos}' and no Address fallback.")

            # 3. Update the document
            if doc_needs_update:
                if dry_run:
                    print(f"[{processed_count}/{total_invoices}] (DRY RUN) {inv.name}: {', '.join(log_msgs)}")
                    updated_count += 1
                else:
                    frappe.db.set_value("Sales Invoice", inv.name, update_data, update_modified=False)
                    updated_count += 1
                    print(f"[{processed_count}/{total_invoices}] UPDATED {inv.name}: {', '.join(log_msgs)}")
            
            elif not log_msgs:
                print(f"[{processed_count}/{total_invoices}] (DRY RUN) {inv.name}: Fields already populated correctly.")

        except Exception as e:
            print(f"  - ERROR: Failed to process {inv.name}: {e}")
            frappe.db.rollback()
            failed_count += 1

        # Commit every 100 records in a live run
        if not dry_run and (i + 1) % 100 == 0:
            frappe.db.commit()
            print(f"--- Committed batch ({i + 1} processed) ---")

    # Final commit
    if not dry_run:
        frappe.db.commit()
        print("--- Final Commit Done. ---")
        
    print("--- Patching Complete! ---")
    print(f"Total Processed: {total_invoices}")
    print(f"Targeted for Update: {updated_count}")
    print(f"Failed: {failed_count}")
    if dry_run:
        print("*** DRY RUN MODE: No changes were saved. ***")

# bench execute entrypoint
def execute(dry_run=True, batch_size=200):
    is_dry_run = bool(dry_run)
    return run_patch(dry_run=is_dry_run)

# bench --site development.localhost execute rohit_common.migration_scripts.patch_invoices.execute --kwargs "{'dry_run': True}"
# bench --site development.localhost execute rohit_common.migration_scripts.patch_invoices.execute --kwargs "{'dry_run': False}"
import frappe
import csv
import os
import json
import math
from typing import Optional
from frappe.utils import now_datetime, flt, get_datetime

# === CONSTANTS ===
SUM_TOLERANCE = 0.5
AMOUNT_MATCH_TOLERANCE = 0.5
GST_START_DATE = "2017-07-01"
# These are the non-tax accounts we found in your data
NON_TAX_ACCOUNTS = [
    "Discount & Rebates - RIGB",
    "Insurance Expenses - RIGB",
    "International Courier Charged - RIGB",
    "Freight & Forwarding Charges - RIGB"
]

# === DOCTYPE MAPPING ===
BASE_DOCTYPE = "Purchase Invoice"
CHILD_DOCTYPE = "Purchase Invoice Item"
TAX_CHILD_DOCTYPE = "Purchase Taxes and Charges"

# ====================================================================
# === PART 1: FILL 'gst_tax_type' IN PURCHASE TAXES AND CHARGES
# ====================================================================

def _first_two_gstin_digits(gstin: Optional[str]) -> Optional[str]:
    if not gstin:
        return None
    gstin = gstin.strip()
    if len(gstin) >= 2 and gstin[:2].isdigit():
        return gstin[:2]
    return None

def _keyword_in(text, keywords):
    if not text:
        return None
    t = text.lower()
    for k in keywords:
        if k.lower() in t:
            return k.lower()
    return None

def infer_tax_type_from_row(tax_row, invoice_doc, company_state_code):
    """
    Return one of 'igst','cgst','sgst','cess' or None if couldn't infer.
    """
    acct = tax_row.get("account_head") or ""
    # Priority 1: keywords in account_head or description
    if _keyword_in(acct, ["IGST", "Integrated GST", "Integrated"] ) :
        return "igst"
    if _keyword_in(acct, ["CGST", "Central GST", "Central"] ) :
        return "cgst"
    if _keyword_in(acct, ["SGST", "State GST", "State"] ) :
        return "sgst"
    if _keyword_in(acct, ["Cess", "Edu. Cess", "SHE Cess", "SBC Service Tax", "KKC Service Tax"] ) :
        return "cess"

    # Priority 2: compare GSTIN state codes (invoice -> company)
    # For Purchase, we compare supplier_gstin to company_gstin (place_of_supply)
    invoice_state_code = None
    if invoice_doc.get("supplier_gstin"):
         invoice_state_code = _first_two_gstin_digits(invoice_doc.get("supplier_gstin"))

    if not invoice_state_code and invoice_doc.get("place_of_supply"):
        pos = invoice_doc.get("place_of_supply")
        if isinstance(pos, str) and len(pos) >= 2 and pos[:2].isdigit():
            invoice_state_code = pos[:2]

    if invoice_state_code and company_state_code:
        if invoice_state_code != company_state_code:
            return "igst"
        else:
            # same state -> likely CGST + SGST.
            return None # Let sibling logic handle this.

    return None

def choose_cgst_or_sgst_by_siblings(tax_rows, idx_missing):
    """
    If some siblings have cgst/sgst, pick the complementary type if possible.
    """
    types = set([r.get("gst_tax_type") for r in tax_rows if r.get("gst_tax_type")])
    if "cgst" in types and "sgst" not in types:
        return "sgst"
    if "sgst" in types and "cgst" not in types:
        return "cgst"
    return None

def run_part_1_fill_gst_tax_type(dry_run=True, batch_size=200, limit=None):
    print(f"\n--- Running Part 1: Repopulating gst_tax_type in {TAX_CHILD_DOCTYPE} ---")
    frappe.flags.in_migrate = True

    limit_clause = f"LIMIT {int(limit)}" if limit else ""
    
    query = f"""
        SELECT DISTINCT t.parent AS name
        FROM `tab{TAX_CHILD_DOCTYPE}` t
        JOIN `tab{BASE_DOCTYPE}` pi ON t.parent = pi.name
        WHERE IFNULL(t.gst_tax_type, '') = ''
          AND t.parenttype = '{BASE_DOCTYPE}'
          AND pi.posting_date >= %(gst_start_date)s
          AND t.account_head NOT IN %(non_tax_accounts)s
        {limit_clause}
        """
        
    invoices = frappe.db.sql(
        query,
        {"gst_start_date": GST_START_DATE, "non_tax_accounts": NON_TAX_ACCOUNTS},
        as_dict=True,
    )

    invoice_names = [r["name"] for r in invoices]
    total_invoices = len(invoice_names)
    print(f"Found {total_invoices} {BASE_DOCTYPE}(s) *since {GST_START_DATE}* with missing gst_tax_type.")

    summary = {
        "part": 1,
        "total_invoices_found": total_invoices,
        "rows_examined": 0,
        "rows_updated": 0,
        "rows_skipped_ambiguous": 0,
        "errors": [],
    }

    updated_count = 0
    processed_invoices = 0

    for inv_name in invoice_names:
        processed_invoices += 1
        try:
            inv = frappe.get_doc(BASE_DOCTYPE, inv_name)
        except Exception as e:
            summary["errors"].append((inv_name, f"read invoice error: {e}"))
            continue

        company_state_code = None
        if inv.get("company_gstin"):
            company_state_code = _first_two_gstin_digits(inv.get("company_gstin"))
        else:
            try:
                comp = frappe.get_doc("Company", inv.get("company"))
                if comp and comp.get("company_gstin"):
                    company_state_code = _first_two_gstin_digits(comp.get("company_gstin"))
            except Exception:
                company_state_code = None

        tax_rows = inv.get("taxes") or []

        invoice_rows_updated = 0
        invoice_rows_skipped = 0
        
        for idx, tax_row in enumerate(tax_rows):
            if tax_row.get("gst_tax_type") or tax_row.account_head in NON_TAX_ACCOUNTS:
                continue
            
            summary["rows_examined"] += 1
            inferred = None
            reason = ""

            inferred = infer_tax_type_from_row(tax_row, inv.as_dict(), company_state_code)
            
            if inferred:
                reason = "keyword_or_state_mismatch"
            else:
                sibling_choice = choose_cgst_or_sgst_by_siblings(tax_rows, idx)
                if sibling_choice:
                    inferred = sibling_choice
                    reason = "sibling_complement"
                else:
                    reason = "ambiguous"

            if inferred:
                if not dry_run:
                    try:
                        frappe.db.set_value(TAX_CHILD_DOCTYPE, tax_row.get("name"), "gst_tax_type", inferred, update_modified=False)
                        updated_count += 1
                        invoice_rows_updated += 1
                        tax_row.gst_tax_type = inferred 
                    except Exception as e:
                        summary["errors"].append((inv_name, tax_row.get("name"), f"update error: {e}"))
            else:
                invoice_rows_skipped += 1

        summary["rows_skipped_ambiguous"] += invoice_rows_skipped

        if not dry_run and invoice_rows_updated > 0 and (processed_invoices % batch_size == 0):
            frappe.db.commit()

    if not dry_run:
        frappe.db.commit()
        print("Part 1: Final commit done.")

    summary["rows_updated"] = updated_count
    print(f"Part 1 Finished. Summary: {summary}")
    return summary


# ====================================================================
# === PART 2: RECONSTRUCT 'Purchase Invoice Item' FROM 'item_wise_tax_detail'
# ====================================================================

def _parse_item_wise_blob_v2(blob):
    if not blob:
        return {}
    if isinstance(blob, dict):
        data = blob
    else:
        try:
            data = json.loads(blob)
        except Exception:
            return {}
    out = {}
    for key, val in data.items():
        if isinstance(val, dict):
            out[key] = {
                "tax_rate": float(val.get("tax_rate") or val.get("rate") or 0) if (val.get("tax_rate") or val.get("rate")) else None,
                "tax_amount": float(val.get("tax_amount")) if val.get("tax_amount") not in (None, "") else None,
                "net_amount": float(val.get("net_amount")) if val.get("net_amount") not in (None, "") else None,
            }
        else:
            try:
                out[key] = {"tax_rate": float(val), "tax_amount": None, "net_amount": None}
            except Exception:
                out[key] = {"tax_rate": None, "tax_amount": None, "net_amount": None}
    return out

def _find_best_item_v2(candidates, inferred_taxable_value, inferred_rate, tol_amount=AMOUNT_MATCH_TOLERANCE):
    if not candidates:
        return None
    best = None
    best_score = None
    for it in candidates:
        tv = flt(it.get("taxable_value") or it.get("amount") or 0)
        nr = flt(it.get("net_rate") or it.get("rate") or 0)
        if inferred_taxable_value:
            diff = abs(tv - inferred_taxable_value)
            if diff <= tol_amount:
                return it
        if inferred_rate and nr is not None:
            diff_rate = abs(nr - inferred_rate)
            if best_score is None or diff_rate < best_score:
                best = it
                best_score = diff_rate
    return best or candidates[0]

def _determine_target_fields_v2(gst_type):
    gst_type = (gst_type or "").lower()
    if gst_type == "igst":
        return "igst_rate", "igst_amount"
    if gst_type == "cgst":
        return "cgst_rate", "cgst_amount"
    if gst_type == "sgst":
        return "sgst_rate", "sgst_amount"
    if gst_type == "cess":
        return "cess_rate", "cess_amount"
    return None, None

def run_part_2_reconstruct_item_taxes(dry_run=True, limit=None, batch_size=200, sum_tolerance=SUM_TOLERANCE):
    print(f"\n--- Running Part 2: Reconstructing {CHILD_DOCTYPE} Taxes ---")
    
    limit_clause = f"LIMIT {int(limit)}" if limit else ""
    
    query = f"""
        SELECT t.name, t.parent as invoice, t.gst_tax_type, t.rate, t.tax_amount, t.item_wise_tax_detail
        FROM `tab{TAX_CHILD_DOCTYPE}` t
        JOIN `tab{BASE_DOCTYPE}` pi ON t.parent = pi.name
        WHERE t.parenttype = '{BASE_DOCTYPE}'
          AND IFNULL(t.tax_amount,0) <> 0
          AND IFNULL(t.item_wise_tax_detail,'') <> ''
          AND IFNULL(t.gst_tax_type,'') != ''
          AND pi.posting_date >= %(gst_start_date)s
        {limit_clause}
    """
    rows = frappe.db.sql(
        query,
        {"gst_start_date": GST_START_DATE},
        as_dict=True
    )

    total = len(rows)
    print(f"Found {total} tax rows (since {GST_START_DATE}) with 'gst_tax_type' and 'item_wise_tax_detail' to process.")
    if total == 0:
        return {"part": 2, "rows_examined": 0, "notes": "No rows found. Did Part 1 run successfully?"}
    
    summary = {
        "part": 2,
        "rows_examined": total,
        "rows_updated": 0,
        "errors": [],
    }
    
    updated = 0
    processed = 0
    invoice_item_cache = {}

    def get_invoice_items(invoice_name):
        if invoice_name not in invoice_item_cache:
            try:
                invoice_item_cache[invoice_name] = frappe.db.sql(f"""
                    SELECT name, item_code, item_name, amount, taxable_value, rate, net_rate, idx,
                           igst_rate, igst_amount, cgst_rate, cgst_amount, 
                           sgst_rate, sgst_amount, cess_rate, cess_amount
                    FROM `tab{CHILD_DOCTYPE}`
                    WHERE parent=%s
                """, invoice_name, as_dict=True)
            except Exception as e:
                summary['errors'].append((invoice_name, f"invoice_read_error: {e}"))
                invoice_item_cache[invoice_name] = None
        return invoice_item_cache[invoice_name]

    for r in rows:
        processed += 1
        tax_row_name = r["name"]
        invoice_name = r["invoice"]
        gst_type = (r.get("gst_tax_type") or "").lower()
        tax_row_rate = flt(r.get("rate") or 0)
        tax_row_amount = flt(r.get("tax_amount") or 0)
        blob = r.get("item_wise_tax_detail") or ""
        parsed = _parse_item_wise_blob_v2(blob)

        sum_itemwise = 0.0
        has_item_amounts = False
        for info in parsed.values():
            if info.get("tax_amount") not in (None, ""):
                has_item_amounts = True
                sum_itemwise += flt(info.get("tax_amount") or 0)

        # ----- STRATEGY 1: Blob has explicit tax_amount -----
        if has_item_amounts:
            if abs(tax_row_amount - sum_itemwise) > sum_tolerance:
                continue # Mismatch sum, skip for safety

            inv_items = get_invoice_items(invoice_name)
            if inv_items is None: continue 

            item_index = {}
            for it in inv_items:
                keys = [str(it.get("name")).strip()]
                if it.get("item_code"): keys.append(str(it.get("item_code")).strip())
                if it.get("item_name"): keys.append(str(it.get("item_name")).strip())
                if it.get("idx"): keys.append(str(int(flt(it.get("idx") or 0))))
                for k in keys:
                    if k: item_index.setdefault(k, []).append(it)

            for item_key, info in parsed.items():
                inferred_tax_amount = info.get("tax_amount")
                inferred_rate = info.get("tax_rate") or tax_row_rate or None
                inferred_taxable_value = info.get("net_amount")
                
                if not inferred_taxable_value and inferred_tax_amount is not None and inferred_rate:
                    try:
                        inferred_taxable_value = round((float(inferred_tax_amount) * 100.0) / float(inferred_rate), 6)
                    except Exception: pass

                candidates = item_index.get(str(item_key).strip(), [])[:]
                if not candidates:
                    for k, lst in item_index.items():
                        if str(item_key).strip().lower() in str(k).strip().lower():
                            candidates.extend(lst)
                
                seen = set(); final_candidates = [c for c in candidates if c.get("name") not in seen and not seen.add(c.get("name"))]
                candidates = final_candidates or inv_items[:]

                best_item = _find_best_item_v2(candidates, inferred_taxable_value, inferred_rate)
                if not best_item:
                    continue

                target_rate_field, target_amount_field = _determine_target_fields_v2(gst_type)
                if not target_rate_field:
                    continue

                before_val = {
                    "taxable_value": flt(best_item.get("taxable_value") or 0),
                    target_rate_field: flt(best_item.get(target_rate_field) or 0),
                    target_amount_field: flt(best_item.get(target_amount_field) or 0)
                }
                
                # *** V5 LOGIC: FORCE OVERWRITE ***
                writes = {}
                # Only write taxable_value if it's currently 0
                if (not before_val["taxable_value"]) and inferred_taxable_value:
                    writes["taxable_value"] = inferred_taxable_value
                
                # Force overwrite tax rates and amounts if they differ
                if inferred_rate is not None and abs(before_val[target_rate_field] - inferred_rate) > 0.01:
                    writes[target_rate_field] = inferred_rate
                if inferred_tax_amount is not None and abs(before_val[target_amount_field] - inferred_tax_amount) > 0.01:
                    writes[target_amount_field] = round(float(inferred_tax_amount), 2)

                if writes:
                    if not dry_run:
                        try:
                            frappe.db.set_value(CHILD_DOCTYPE, best_item.get("name"), writes, update_modified=False)
                            updated += len(writes) # Count each field update
                        except Exception as e:
                            summary['errors'].append((invoice_name, best_item.get("name"), f"write_error: {e}"))
                    else:
                        updated += len(writes) # Count presumed updates

        # ----- STRATEGY 2: Blob has NO explicit tax_amount (rate-only) -----
        else:
            inv_items = get_invoice_items(invoice_name)
            if inv_items is None: continue

            item_index = {}
            for it in inv_items:
                keys = [str(it.get("name")).strip()]
                if it.get("item_code"): keys.append(str(it.get("item_code")).strip())
                if it.get("item_name"): keys.append(str(it.get("item_name")).strip())
                if it.get("idx"): keys.append(str(int(flt(it.get("idx") or 0))))
                for k in keys:
                    if k: item_index.setdefault(k, []).append(it)
            
            inferred_rows = []
            sum_inferred = 0.0
            for item_key, info in parsed.items():
                rate_only = info.get("tax_rate")
                if not rate_only or rate_only == 0: continue

                candidates = item_index.get(str(item_key).strip(), [])[:]
                if not candidates:
                    for k, lst in item_index.items():
                        if str(item_key).strip().lower() in str(k).strip().lower():
                            candidates.extend(lst)
                
                seen = set(); final_candidates = [c for c in candidates if c.get("name") not in seen and not seen.add(c.get("name"))]
                candidates = final_candidates or inv_items[:]

                best_item = _find_best_item_v2(candidates, None, rate_only)
                if not best_item: continue

                tv = flt(best_item.get("taxable_value") or 0)
                if not tv: tv = flt(best_item.get("amount") or 0)
                if not tv or tv == 0: continue

                inferred_tax_amount = round((tv * float(rate_only) / 100.0), 2)
                inferred_rows.append((best_item, rate_only, tv, inferred_tax_amount, item_key))
                sum_inferred += inferred_tax_amount

            if not inferred_rows:
                continue

            if abs(sum_inferred - tax_row_amount) > sum_tolerance:
                continue

            for best_item, rate_used, tv, inferred_tax_amount, item_key in inferred_rows:
                target_rate_field, target_amount_field = _determine_target_fields_v2(gst_type)
                if not target_rate_field: continue

                before_val = {
                    "taxable_value": flt(best_item.get("taxable_value") or 0),
                    target_rate_field: flt(best_item.get(target_rate_field) or 0),
                    target_amount_field: flt(best_item.get(target_amount_field) or 0)
                }

                # *** V5 LOGIC: FORCE OVERWRITE ***
                writes = {}
                if tv is not None and (not before_val["taxable_value"]): # Only write taxable if 0
                    writes["taxable_value"] = tv
                if rate_used is not None and abs(before_val[target_rate_field] - rate_used) > 0.01:
                    writes[target_rate_field] = rate_used
                if inferred_tax_amount is not None and abs(before_val[target_amount_field] - inferred_tax_amount) > 0.01:
                    writes[target_amount_field] = inferred_tax_amount

                if writes:
                    if not dry_run:
                        try:
                            frappe.db.set_value(CHILD_DOCTYPE, best_item.get("name"), writes, update_modified=False)
                            updated += len(writes) # Count each field update
                        except Exception as e:
                            summary['errors'].append((invoice_name, best_item.get("name"), f"write_error: {e}"))
                    else:
                        updated += len(writes)

        if not dry_run and (updated and (processed % batch_size == 0)):
            frappe.db.commit()
            if processed % (batch_size * 5) == 0: 
                print(f"  ... Part 2 processing: {processed}/{total} tax rows processed, {updated} items updated.")

    if not dry_run:
        frappe.db.commit()
        print("Part 2: Final commit done.")

    summary['rows_updated'] = updated
    print(f"Part 2 Finished. Summary: {summary}")
    return summary


# ====================================================================
# === MAIN EXECUTE FUNCTION
# ====================================================================

def execute(dry_run=True, batch_size=200, limit=None, sum_tolerance=SUM_TOLERANCE):
    """
    Main execution function to fix Purchase Invoice GST data.
    """
    dry_run = bool(dry_run)
    batch_size = int(batch_size) if batch_size else 200
    limit = int(limit) if limit else None
    sum_tolerance = float(sum_tolerance) if sum_tolerance else SUM_TOLERANCE

    print(f"*** STARTING PURCHASE INVOICE GST DATA RECONSTRUCTION ***")
    print(f"*** {'DRY RUN' if dry_run else 'APPLYING CHANGES'} ***")
    print(f"*** (Note: Processing is limited to invoices on or after {GST_START_DATE}) ***")

    summary1 = {}
    summary2 = {}
    
    # --- Part 1 ---
    try:
        summary1 = run_part_1_fill_gst_tax_type(dry_run=dry_run, batch_size=batch_size, limit=limit)
        print("\n=== Part 1 Summary ===")
        print(json.dumps(summary1, indent=2, default=str))
    except Exception as e:
        print(f"\n*** ERROR in Part 1 (fill_gst_tax_type): {e} ***")
        frappe.log_error(title="GST Fix Script Part 1 Failed")
        frappe.db.rollback()
        return {"error": "Part 1 Failed", "details": str(e)}

    # --- Part 2 ---
    try:
        summary2 = run_part_2_reconstruct_item_taxes(dry_run=dry_run, limit=limit, batch_size=batch_size, sum_tolerance=sum_tolerance)
        print("\n=== Part 2 Summary ===")
        print(json.dumps(summary2, indent=2, default=str))
    except Exception as e:
        print(f"\n*** ERROR in Part 2 (reconstruct_item_taxes): {e} ***")
        frappe.log_error(title="GST Fix Script Part 2 Failed")
        frappe.db.rollback()
        return {"error": "Part 2 Failed", "details": str(e)}

    if dry_run:
        print("\n*** DRY RUN COMPLETE. No changes were made. Rolling back. ***")
        frappe.db.rollback()
    else:
        print("\n*** ALL PARTS COMPLETE. Final commit issued. ***")
        frappe.db.commit()

    print("\n--- SCRIPT FINISHED ---")
    return {"part1_summary": summary1, "part2_summary": summary2}


# bench --site development.localhost execute rohit_common.migration_scripts.fix_purchase_invoices_gst.execute \
#   --kwargs "{'dry_run': True, 'limit': 100}"

# bench --site development.localhost execute rohit_common.migration_scripts.fix_purchase_invoices_gst.execute \
#   --kwargs "{'dry_run': False}"
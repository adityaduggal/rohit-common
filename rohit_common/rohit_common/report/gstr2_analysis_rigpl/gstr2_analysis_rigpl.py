#  Copyright (c) 2021. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe.utils import getdate, flt
from datetime import datetime


def execute(filters=None):
	columns = get_columns(filters)
	data = get_data(filters)
	return columns, data


def get_data(filters):
	data = []
	if filters.get("as_per_gstin") != 1:
		cond = get_conditions(filters)
		gst_set = frappe.get_doc("GST Settings", "GST Setting")
		gst_taxes = []
		for d in gst_set.gst_accounts:
			for field in ["cgst_account", "sgst_account", "igst_account", "cess_account"]:
				acc = d.get(field)
				if acc and "Input" in acc:
					gst_taxes.append(acc)
		
		gst_taxes = list(set(gst_taxes))
		if not gst_taxes:
			return []

		# Fetch all relevant GL entries first
		all_gl_entries = frappe.db.sql("""
			SELECT 
				name, posting_date, account, debit_in_account_currency as debit, 
				credit_in_account_currency as credit, voucher_type, voucher_no 
			FROM `tabGL Entry` gl
			WHERE docstatus = 1 AND gl.account IN (%s) %s 
			ORDER BY gl.posting_date, gl.name
		""" % (', '.join(['%s']*len(gst_taxes)), cond), tuple(gst_taxes), as_dict=1)

		if not all_gl_entries:
			return []

		# Collect unique vouchers for bulk fetching
		vouchers_by_type = {}
		for gl in all_gl_entries:
			vouchers_by_type.setdefault(gl.voucher_type, set()).add(gl.voucher_no)

		# Bulk fetch Purchase Invoice details
		pi_details = {}
		if "Purchase Invoice" in vouchers_by_type:
			pi_data = frappe.get_all("Purchase Invoice", 
				filters={"name": ["in", list(vouchers_by_type["Purchase Invoice"])]},
				fields=["name", "supplier", "supplier_gstin", "bill_no", "bill_date", 
						"base_grand_total", "base_net_total", "shipping_address"])
			pi_details = {d.name: d for d in pi_data}

		# Bulk fetch Non-PI Grand Totals (total_debit)
		non_pi_totals = {}
		for vtype, vnos in vouchers_by_type.items():
			if vtype != "Purchase Invoice":
				try:
					# Standard vouchers have a total_debit or base_grand_total field
					fields = ["name", "total_debit"]
					if vtype == "Journal Entry":
						fields = ["name", "total_debit"]
					
					totals_data = frappe.get_all(vtype, filters={"name": ["in", list(vnos)]}, fields=fields)
					for t in totals_data:
						non_pi_totals[(vtype, t.name)] = t.get(fields[1], 0)
				except Exception:
					pass

		# Bulk fetch GSTR2 details
		gstr2_map = get_bulk_gstr2_details(vouchers_by_type, pi_details)
		
		main_gl_map = {} # Key: (voucher_type, voucher_no)

		for gl in all_gl_entries:
			key = (gl.voucher_type, gl.voucher_no)
			
			if key not in main_gl_map:
				# Initialize entry with basic details and party info
				entry = gl.copy()
				if gl.voucher_type == "Purchase Invoice":
					pi = pi_details.get(gl.voucher_no)
					if pi:
						entry.update({
							"party_type": "Supplier",
							"party": pi.supplier,
							"party_gstin": pi.supplier_gstin,
							"sup_inv_no": pi.bill_no,
							"sup_inv_date": pi.bill_date,
							"doc_gt": pi.base_grand_total,
							"doc_nt": pi.base_net_total
						})
				else:
					entry["doc_gt"] = non_pi_totals.get((gl.voucher_type, gl.voucher_no), 0)

				# Apply GSTR2 data if found
				gstr2_info = gstr2_map.get(key)
				if gstr2_info:
					mf = -1 if gstr2_info.note_type == "Credit Note" else 1
					entry.update({
						"gstr1_stat": gstr2_info.filing_status_gstr1,
						"gstr2b_date": gstr2_info.gstr2b_date,
						"gstr2b_period": gstr2_info.gstr2b_period,
						"period_gstr1": gstr2_info.filing_period_gstr1,
						"note_type": gstr2_info.note_type,
						"gstr3b_stat": 1 if gstr2_info.note_type == "Bill of Entry" else gstr2_info.filing_status_gstr3b,
						"gstr1_fil_date": gstr2_info.supplier_invoice_date if gstr2_info.note_type == "Bill of Entry" else gstr2_info.filing_date_gstr1,
						"gstr2_gt": gstr2_info.grand_total * mf,
						"gstr2_nt": gstr2_info.taxable_value * mf,
						"gstr2_igst": gstr2_info.igst_amount * mf,
						"gstr2_cgst": gstr2_info.cgst_amount * mf,
						"gstr2_sgst": gstr2_info.sgst_amount * mf,
						"gstr2_cess": gstr2_info.cess_amount * mf,
						"gstr2a_name": gstr2_info.parent
					})
					
					if gstr2_info.note_type == "Bill of Entry":
						entry["sup_inv_date"] = gstr2_info.supplier_invoice_date
						entry["sup_inv_no"] = gstr2_info.supplier_invoice_no
						entry["party_gstin"] = gstr2_info.party_gstin

				# Initialize tax buckets
				for tax_field in ["doc_igst", "doc_sgst", "doc_cgst", "doc_cess", "doc_tot_tax"]:
					entry[tax_field] = 0
				
				main_gl_map[key] = entry

			# Accumulate tax from the current GL entry
			entry = main_gl_map[key]
			tax_val = gl.debit if gl.debit > 0 else -gl.credit
			
			if "IGST" in gl.account:
				entry["doc_igst"] += tax_val
			elif "CGST" in gl.account:
				entry["doc_cgst"] += tax_val
			elif "SGST" in gl.account:
				entry["doc_sgst"] += tax_val
			elif "CESS" in gl.account:
				entry["doc_cess"] += tax_val
			
			entry["doc_tot_tax"] += tax_val

		# Final Row Assembly
		for gl in main_gl_map.values():
			gstr2_tot_tax = flt(gl.get("gstr2_igst", 0)) + flt(gl.get("gstr2_cgst", 0)) + \
							flt(gl.get("gstr2_sgst", 0)) + flt(gl.get("gstr2_cess", 0))
			
			row = [
				gl.posting_date, gl.voucher_no, gl.get("party", ""),
				gl.get("gstr1_stat", 0), gl.get("gstr1_fil_date", "1900-01-01"),
				gl.get("period_gstr1", ""), gl.get("gstr2b_date", "1900-01-01"),
				gl.get("gstr2b_period", "X"), gl.get("gstr3b_stat", 0),
				gl.get("party_gstin", ""), gl.get("note_type", "X"), gl.get("sup_inv_no", ""),
				gl.get("sup_inv_date", "1900-01-01"),
				gl.get("gstr2_gt", 0), gl.get("gstr2_nt", 0), gl.get("gstr2_igst", 0), gl.get("gstr2_cgst", 0),
				gl.get("gstr2_sgst", 0), gl.get("gstr2_cess", 0), gstr2_tot_tax, gl.get("doc_gt", 0),
				gl.get("doc_nt", 0), gl.get("doc_igst", 0), gl.get("doc_cgst", 0), gl.get("doc_sgst", 0),
				gl.get("doc_cess", 0), gl.get("doc_tot_tax", 0), gl.voucher_type, gl.get("party_type", ""),
				gl.get("gstr2a_name", "")
			]
			data.append(row)
	else:
		# GSTIN Wise logic remains mostly as is but uses parameter binding
		ret_period = get_ret_period(filters)
		cond = ""
		if getdate(filters.get("from_date")) < datetime.strptime("01-07-2020", "%d-%m-%Y").date():
			cond = " AND gri.filing_period_gstr1 = %(ret_period)s AND gri.gstr2b_period IS NULL"
		else:
			cond = " AND gri.gstr2b_period = %(ret_period)s"
			
		gstr2ab = frappe.db.sql("""
			SELECT gr.name, gri.gstr2b_period, gri.party_type, gri.party, gri.party_gstin, gri.note_type, 
			gri.supplier_invoice_no, gri.supplier_invoice_date, gri.linked_document_type, gri.linked_document_name,
			gri.posting_date, gri.grand_total, gri.taxable_value, gri.igst_amount, gri.cgst_amount, gri.sgst_amount, 
			gri.cess_amount, gri.filing_date_gstr1, gri.gstr2b_date, gri.filing_status_gstr3b, gri.filing_period_gstr1
			FROM `tabGSTR2A RIGPL` gr, `tabGSTR2 Return Invoices` gri
			WHERE gri.parent = gr.name AND gr.docstatus < 2 %s
			ORDER BY gri.party, gri.posting_date
		""" % cond, {"ret_period": ret_period}, as_dict=1)

		for d in gstr2ab:
			mf = -1 if d.note_type == "Credit Note" else 1
			row = [d.posting_date, d.linked_document_name, d.party, 1, d.filing_date_gstr1, d.filing_period_gstr1,
				   d.gstr2b_date, d.gstr2b_period, d.filing_status_gstr3b, d.party_gstin, d.note_type,
				   d.supplier_invoice_no, d.supplier_invoice_date, d.grand_total*mf, d.taxable_value*mf,
				   d.igst_amount*mf, d.cgst_amount*mf, d.sgst_amount*mf, d.cess_amount*mf,
				   mf*(d.igst_amount + d.cgst_amount + d.sgst_amount + d.cess_amount), 0, 0, 0, 0, 0, 0, 0,
				   d.linked_document_type, d.party_type, d.name]
			data.append(row)
	return data


def get_bulk_gstr2_details(vouchers_by_type, pi_details):
	gstr2_map = {}
	
	# Pre-fetch address GSTINs
	address_map = {}
	relevant_addresses = [d.shipping_address for d in pi_details.values() if d.shipping_address]
	if relevant_addresses:
		addr_data = frappe.get_all("Address", 
			filters={"name": ["in", relevant_addresses]}, 
			fields=["name", "gstin"])
		address_map = {d.name: d.gstin for d in addr_data}

	# Gather all possible matching numbers (Voucher Nos + Bill Nos)
	matches = []
	for v_list in vouchers_by_type.values():
		matches.extend(list(v_list))
	for pi in pi_details.values():
		if pi.bill_no:
			matches.append(pi.bill_no)
	
	if not matches:
		return {}

	# Fetch ALL potential GSTR2 matches in one go
	res = frappe.db.sql("""
		SELECT gstri.*, gstr.gstin as receiver_gstin
		FROM `tabGSTR2 Return Invoices` gstri
		JOIN `tabGSTR2A RIGPL` gstr ON gstri.parent = gstr.name
		WHERE gstr.docstatus != 2 
		AND (gstri.linked_document_name IN %(matches)s OR gstri.supplier_invoice_no IN %(matches)s)
	""", {"matches": list(set(matches))}, as_dict=1)

	# Replicate the strict mapping logic in Python memory
	for vtype, vnos_set in vouchers_by_type.items():
		for vno in vnos_set:
			if vtype == "Purchase Invoice":
				pi = pi_details.get(vno)
				if not pi: continue
				self_gstin = address_map.get(pi.shipping_address)
				
				# Check for a match using the 4 strict PI rules
				for d in res:
					if d.receiver_gstin == self_gstin and d.party == pi.supplier and d.party_type == "Supplier":
						if d.linked_document_name == vno or (pi.bill_no and d.supplier_invoice_no == pi.bill_no):
							gstr2_map[(vtype, vno)] = d
							break
			else:
				# Standard matching for Non-PI vouchers
				for d in res:
					if d.linked_document_type == vtype and d.linked_document_name == vno:
						gstr2_map[(vtype, vno)] = d
						break

	return gstr2_map


def get_ret_period(filters):
	frm_date = getdate(filters.get("from_date"))
	frm_mth = frm_date.month
	to_mth = getdate(filters.get("to_date")).month
	if frm_date.year != getdate(filters.get("to_date")).year:
		frappe.throw("For GST Wise Input Months for Both From Date and To Date should be From Same Year")
	if frm_mth != to_mth:
		frappe.throw("For GST Wise Input Months for Both From Date and To Date should be From Same Month")
	else:
		if frm_date >= datetime.strptime("01-07-2020", "%d-%m-%Y").date():
			ret_period = str(frm_mth) + str(getdate(filters.get("from_date")).year)
			if frm_mth < 10:
				return "0" + ret_period
			else:
				return ret_period
		else:
			return datetime.strftime(frm_date, "%b") + "-" + datetime.strftime(frm_date, "%y")


def get_columns(filters):
	columns = [
		"Posting Date:Date:80",
		{
			"label": "Voucher No",
			"fieldname": "voucher_no",
			"fieldtype": "Dynamic Link",
			"options": "voucher_type",
			"width": 130
		},
		{
			"label": "Party",
			"fieldname": "party",
			"fieldtype": "Dynamic Link",
			"options": "party_type",
			"width": 250
		},
		"GSTR1 Status:Int:30", "GSTR1 Filing Date:Date:80", "GSTR1 Period::80", "GSTR2B Date:Date:80",
		"GSTR2B Period::80",
		"GSTR3B Status:Int:30", "Party GSTIN::180", "Type::80",
		"Supplier Inv#::120", "Supplier Inv Date:Date:80", "GSTR2-GT:Currency:120", "GSTR2-NT:Currency:120",
		"GSTR2-IGST:Currency:120", "GSTR2-CGST:Currency:120", "GSTR2-SGST:Currency:120", "GSTR2-Cess:Currency:120",
		"GSTR2-Total Tax:Currency:120",
		"Doc-GT:Currency:120", "Doc-NT:Currency:120", "Doc-IGST:Currency:120", "Doc-CGST:Currency:120",
		"Doc-SGST:Currency:120", "Doc-Cess:Currency:120", "Doc-Total Tax:Currency:120",
		{
			"label": "Voucher Type",
			"fieldname": "voucher_type",
			"width": 1
		},
		{
			"label": "Party Type",
			"fieldname": "party_type",
			"width": 1
		}, "GSTR2 Link:Link/GSTR2A RIGPL:250"
	]
	return columns


def get_conditions(filters):
	cond = ""
	max_diff = 32
	days = (getdate(filters.get('to_date')) - getdate(filters.get('from_date'))).days
	if days <= 0:
		frappe.throw(f"To Date has to be Greater than From Date")
	elif days >= max_diff:
		frappe.throw(f"Difference between To and From Date Cannot be more than {max_diff} days")
	else:
		cond += " AND gl.posting_date >= '%s'" % filters.get("from_date")
		cond += " AND gl.posting_date <= '%s'" % filters.get("to_date")
	return cond

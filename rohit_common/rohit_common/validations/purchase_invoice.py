#  Copyright (c) 2021. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-

from __future__ import unicode_literals
import frappe
from .sales_invoice import check_validated_gstin


def validate(doc,method):
	update_fields(doc,method)
	check_gst_rules(doc,method)
	check_taxes_integrity(doc,method)
	add_list = [doc.shipping_address, doc.supplier_address]
	for add in add_list:
		check_validated_gstin(add, doc)


def check_gst_rules(doc,method):
	ship_state = frappe.db.get_value("Address", doc.shipping_address, "state_rigpl")
	template_doc = frappe.get_doc("Purchase Taxes and Charges Template", doc.taxes_and_charges)
	doc.billing_address = template_doc.from_address
	bill_add_doc = frappe.get_doc('Address', doc.billing_address)
	doc.company_gstin = bill_add_doc.gstin
	ship_country = frappe.db.get_value("Address", doc.shipping_address, "country")
	supplier_state = frappe.db.get_value("Address", doc.supplier_address, "state_rigpl")
	supplier_country = frappe.db.get_value("Address", doc.supplier_address, "country")

	series_template = frappe.db.get_value("Purchase Taxes and Charges Template", doc.taxes_and_charges ,"series")

	# Check series of Tax with the Series Selected for Invoice
	if series_template != doc.naming_series[2:4] and series_template != doc.name[2:4]:
		frappe.throw(("Selected Tax Template {0} Not Allowed since Series Selected {1} and \
			PO number {2} don't match with the Selected Template").format(doc.taxes_and_charges, doc.naming_series,
																		  doc.name))
	
	if doc.taxes_and_charges != 'OGL':
		# Check if Shipping State is Same as Template State then check if the tax template is LOCAL
		# Else if the States are different then the template should NOT BE LOCAL
		# Compare the Ship State with the Tax Template (since Shipping address is our own address)
		# if Ship State is Same as Supplier State then Local else Central or Import
		if ship_state != template_doc.state:
			frappe.throw("Selected Tax template is not for Selected Shipping Address")

		if template_doc.state == supplier_state:
			if template_doc.is_local_purchase != 1 and template_doc.is_import != 1:
				frappe.throw(("Selected Tax {0} is NOT LOCAL Tax but Supplier Address is \
					in Same State {1}, hence either change Supplier Address or Change the \
					Selected Tax").format(doc.taxes_and_charges, supplier_state))
		elif supplier_country == 'India' and supplier_state != template_doc.state and template_doc.is_import != 1:
			if template_doc.is_local_purchase == 1:
				frappe.throw(("Selected Tax {0} is LOCAL Tax but Supplier Address is \
					in Different State {1}, hence either change Supplier Address or Change the \
					Selected Tax").format(doc.taxes_and_charges, supplier_state))
		elif supplier_country != 'India': #Case of IMPORTS
			if template_doc.is_import != 1:
				frappe.throw(("Selected Tax {0} is for Indian Sales but Supplier Address is \
					in Different Country {1}, hence either change Supplier Address or Change the \
					Selected Tax").format(doc.taxes_and_charges, supplier_country))


def update_fields(doc,method):
	for it in doc.items:
		it_gst = frappe.get_value('Item', it.item_code, 'customs_tariff_number')
		if it.gst_hsn_code != it_gst:
			it.gst_hsn_code = it_gst
	doc.letter_head = frappe.db.get_value("Purchase Taxes and Charges Template", doc.taxes_and_charges, "letter_head")
	# doc.place_of_supply = frappe.db.get_value("Purchase Taxes and Charges Template", doc.taxes_and_charges, "state")
	doc.supplier_gstin = frappe.db.get_value("Address", doc.supplier_address, "gstin")
	doc.company_gstin = frappe.db.get_value("Address", doc.shipping_address, "gstin")


def check_taxes_integrity(doc,method):
	template = frappe.get_doc("Purchase Taxes and Charges Template", doc.taxes_and_charges)
	for tax in doc.taxes:
		check = 0
		for temp in template.taxes:
			if tax.idx == temp.idx and check == 0:
				check = 1
				if tax.charge_type != temp.charge_type or tax.row_id != temp.row_id or tax.account_head != \
						temp.account_head or tax.included_in_print_rate != temp.included_in_print_rate or \
						tax.add_deduct_tax != temp.add_deduct_tax:
						frappe.throw(("Selected Tax {0}'s table does not match with tax table \
							of PO# {1}. Check Row # {2} or reload Taxes").\
							format(doc.taxes_and_charges, doc.name, tax.idx))
		if check == 0:
			frappe.throw(("Selected Tax {0}'s table does not match with tax table \
				of PO# {1}. Check Row # {2} or reload Taxes").\
				format(doc.taxes_and_charges, doc.name, tax.idx))
# Copyright (c) 2021, Rohit Industries Group Private Limited and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import msgprint, _

def execute(filters=None):
    columns = get_columns(filters)
    data = get_data(filters)
    return columns, data

def get_columns(filters):
    if filters.get("type") == 'Sales Invoice':
        if filters.get("item_wise") == 1:
            columns = [
                            _("Invoice Number") + ":Link/Sales Invoice:100",
                            _("Invoice Date") + ":Date:80", _("Grand Total") + ":Currency:80",
                            _("Net Total") + ":Currency:80", _("Customer") + ":Link/Customer:200",
                            _("Ship Address") + ":Link/Address:200",
                            _("Tax") + ":Link/Sales Taxes and Charges Template:150",
                            _("Ship Country") + ":Link/Country:150"
                    ]
        elif filters.get("hsn") == 1:
            columns = [
                            _("Item Code") + ":Link/Item:100",
                            _("HSN Code") + "::80", _("Quantity") + ":Float:80", _("UoM") + "::80",
                            _("Grand Total") + ":Currency:120", _("Net Total") + ":Currency:120",
                            _("IGST Amount") + ":Currency:120", _("CGST Amount") + ":Currency:120",
                            _("SGST Amount") + ":Currency:120"
                    ]
        else:
            columns = [
                    _("Invoice Date") + ":Date:90", _("Invoice Number") + ":Link/Sales Invoice:120",
                    _("Net Total") + ":Currency:100", _("Grand Total") + ":Currency:100",
                    _("Customer Link") + ":Link/Customer:100",
                    _("Tax Link") + ":Link/Sales Taxes and Charges Template:100",
                    _("Is Export") + "::30", _("GST Paid on Export") + "::30",
                    _("Export Shipping Bill Number") + "::80", _("Export Shipping Bill Date") + ":Date:80",
                    _("Export Shipping Bill Port Code") + "::80", _("Export Destination Country Code") + "::80",
                    _("Billing Address Link") + ":Link/Address:80", _("Billing Name") + "::80",
                    _("Billing City") + "::80", _("Billing Pincode") + "::60", _("Billing State") + "::80",
                    _("Billing GSTIN") + "::140",
                    _("Shipping Address Link") + ":Link/Address:80", _("Shipping Name") + "::80",
                    _("Shipping City") + "::80", _("Shipping Pincode") + "::60", _("Shipping State") + "::80",
                    _("Shipping GSTIN") + "::140",
                    _("CGST Rate") + ":Percent:50", _("CGST Amount") + ":Currency:80",
                    _("SGST Rate") + ":Percent:50", _("SGST Amount") + ":Currency:80",
                    _("IGST Rate") + ":Percent:50", _("IGST Amount") + ":Currency:80"
                    ]
    elif filters.get("type") == 'Purchase Invoice':
        columns = [
                _("PI Posting Date") + ":Date:70", _("PI Number") + ":Link/Purchase Invoice:70",
                _("Supplier PI Date") + ":Date:70", _("Supplier PI No") + "::70",
                _("Net Total") + ":Currency:100", _("Grand Total") + ":Currency:100",
                _("Supplier Link") + ":Link/Supplier:100",
                _("Tax Link") + ":Link/Purchase Taxes and Charges Template:100",
                _("Supplier GSTIN") + "::100", _("State of Supply") + "::100",
                _("Is Import") + "::30", _("ITC Claim Type") + "::50",
                _("CGST Claim Amount") + ":Currency:50", _("SGST Claim Amount") + ":Currency:50",
                _("IGST Claim Amount") + ":Currency:50",
                ]
    return columns

def get_data(filters):
    si_cond, pi_cond = get_conditions(filters)
    data = []

    if filters.get("type") == 'Sales Invoice':
        if filters.get("item_wise") == 1:
            data = frappe.db.sql("""
                SELECT 
                    si.name, si.posting_date, si.base_net_total,
                    si.base_grand_total, si.customer, si.shipping_address_name, si.taxes_and_charges,
                    ad.country
                FROM `tabSales Invoice` si
                JOIN `tabSales Taxes and Charges Template` stct ON stct.name = si.taxes_and_charges
                JOIN `tabAddress` ad ON ad.name = si.shipping_address_name
                WHERE si.docstatus = 1 AND stct.is_export = 1 %s
                ORDER BY si.posting_date, si.name
            """ % si_cond, as_list=1)
            
        elif filters.get("hsn") == 1:
            data = frappe.db.sql("""
                SELECT 
                    sid.item_code, it.customs_tariff_number, SUM(sid.qty),
                    it.stock_uom, SUM(sid.base_amount), SUM(sid.base_net_amount)
                FROM `tabSales Invoice Item` sid
                JOIN `tabSales Invoice` si ON sid.parent = si.name
                JOIN `tabItem` it ON sid.item_code = it.name
                WHERE si.docstatus = 1 %s
                GROUP BY sid.item_code
                ORDER BY sid.item_code
            """ % si_cond, as_list=1)
            
        else:
            # 1. Fetch Invoice Headers first (Targeted Fetch)
            invoice_headers = frappe.db.sql("""
                SELECT 
                    si.posting_date, si.name, si.base_net_total,
                    si.base_grand_total, si.customer, si.taxes_and_charges,
                    IF(tax_template.is_export = 1, 'Y', '') as is_export,
                    IF(tax_template.is_export = 1, 'Export with Payment of GST or Export without Payment of GST or SEZ or Deemed Export', '') as export_text,
                    IF(tax_template.is_export = 1, si.shipping_bill_number, '') as shipping_bill_number,
                    IF(tax_template.is_export = 1, si.shipping_bill_date, '') as shipping_bill_date,
                    IF(tax_template.is_export = 1, si.port_code, '') as port_code,
                    IF(tax_template.is_export = 1, cn.code, '') as country_code,
                    si.customer_address, 
                    ad.address_title as billing_name, ad.city as billing_city, ad.pincode as billing_pincode, ad.state_rigpl as billing_state, ad.gstin as billing_gstin,
                    si.shipping_address_name, 
                    ad2.address_title as shipping_name, ad2.city as shipping_city, ad2.pincode as shipping_pincode, ad2.state_rigpl as shipping_state, ad2.gstin as shipping_gstin
                FROM `tabSales Invoice` si
                INNER JOIN `tabSales Taxes and Charges Template` tax_template ON si.taxes_and_charges = tax_template.name
                LEFT JOIN `tabAddress` ad ON ad.name = si.customer_address
                LEFT JOIN `tabAddress` ad2 ON ad2.name = si.shipping_address_name
                LEFT JOIN `tabCountry` cn ON cn.name = ad.country
                WHERE si.docstatus != 2 %s
                ORDER BY si.posting_date, si.name
            """ % si_cond, as_dict=1)

            if not invoice_headers:
                return []

            # 2. Bulk fetch only required tax entries (Efficient)
            invoice_names = [d['name'] for d in invoice_headers]
            taxes_query = """
                SELECT 
                    parent,
                    rate,
                    base_tax_amount_after_discount_amount as amount,
                    (account_head LIKE '%%CGST%%' OR description LIKE '%%CGST%%') as is_cgst,
                    (account_head LIKE '%%SGST%%' OR description LIKE '%%SGST%%') as is_sgst,
                    (account_head LIKE '%%IGST%%' OR description LIKE '%%IGST%%') as is_igst
                FROM `tabSales Taxes and Charges`
                WHERE parent IN ({})
            """.format(", ".join(["%s"] * len(invoice_names)))
            
            taxes = frappe.db.sql(taxes_query, tuple(invoice_names), as_dict=1)

            # 3. Aggregate in Python (O(N) Complexity)
            tax_map = {}
            for t in taxes:
                p = t['parent']
                if p not in tax_map:
                    tax_map[p] = {'cr': 0, 'ca': 0, 'sr': 0, 'sa': 0, 'ir': 0, 'ia': 0}
                
                if t['is_cgst']:
                    tax_map[p]['cr'] = max(tax_map[p]['cr'], t['rate'])
                    tax_map[p]['ca'] += t['amount']
                elif t['is_sgst']:
                    tax_map[p]['sr'] = max(tax_map[p]['sr'], t['rate'])
                    tax_map[p]['sa'] += t['amount']
                elif t['is_igst']:
                    tax_map[p]['ir'] = max(tax_map[p]['ir'], t['rate'])
                    tax_map[p]['ia'] += t['amount']

            # 4. Assembly
            for d in invoice_headers:
                t = tax_map.get(d['name'], {'cr': 0, 'ca': 0, 'sr': 0, 'sa': 0, 'ir': 0, 'ia': 0})
                row = [
                    d['posting_date'], d['name'], d['base_net_total'], d['base_grand_total'],
                    d['customer'], d['taxes_and_charges'], d.get('is_export'),
                    d.get('export_text'),
                    d.get('shipping_bill_number'),
                    d.get('shipping_bill_date'),
                    d.get('port_code'),
                    d.get('country_code'),
                    d['customer_address'], d['billing_name'], d['billing_city'], d['billing_pincode'], d['billing_state'], d['billing_gstin'],
                    d['shipping_address_name'], d['shipping_name'], d['shipping_city'], d['shipping_pincode'], d['shipping_state'], d['shipping_gstin'],
                    t['cr'], t['ca'], t['sr'], t['sa'], t['ir'], t['ia']
                ]
                data.append(row)
            
    elif filters.get("type") == 'Purchase Invoice':
        invoice_headers = frappe.db.sql("""
            SELECT 
                pi.posting_date, pi.name,
                pi.bill_date, pi.bill_no, pi.base_net_total,
                pi.base_grand_total, pi.supplier, pi.taxes_and_charges,
                IFNULL(adb.gstin, "NA") as gstin, 
                IFNULL(ads.state_rigpl, "X") as state,
                IF(tax_template.is_import = 1, 'Y', 'N') as is_import
            FROM `tabPurchase Invoice` pi
            INNER JOIN `tabPurchase Taxes and Charges Template` tax_template ON pi.taxes_and_charges = tax_template.name
            LEFT JOIN `tabAddress` adb ON adb.name = pi.supplier_address
            LEFT JOIN `tabAddress` ads ON ads.name = pi.shipping_address
            WHERE pi.docstatus != 2 %s
            ORDER BY pi.posting_date, pi.name
        """ % pi_cond, as_dict=1)

        if not invoice_headers:
            return []

        invoice_names = [d['name'] for d in invoice_headers]
        taxes_query = """
            SELECT 
                parent,
                base_tax_amount_after_discount_amount as amount,
                (account_head LIKE '%%CGST%%' OR description LIKE '%%CGST%%') as is_cgst,
                (account_head LIKE '%%SGST%%' OR description LIKE '%%SGST%%') as is_sgst,
                (account_head LIKE '%%IGST%%' OR description LIKE '%%IGST%%') as is_igst
            FROM `tabPurchase Taxes and Charges`
            WHERE parent IN ({})
        """.format(", ".join(["%s"] * len(invoice_names)))
        
        taxes = frappe.db.sql(taxes_query, tuple(invoice_names), as_dict=1)

        tax_map = {}
        for t in taxes:
            p = t['parent']
            if p not in tax_map:
                tax_map[p] = {'ca': 0, 'sa': 0, 'ia': 0}
            if t['is_cgst']: tax_map[p]['ca'] += t['amount']
            elif t['is_sgst']: tax_map[p]['sa'] += t['amount']
            elif t['is_igst']: tax_map[p]['ia'] += t['amount']

        for d in invoice_headers:
            t = tax_map.get(d['name'], {'ca': 0, 'sa': 0, 'ia': 0})
            row = [
                d['posting_date'], d['name'], d['bill_date'], d['bill_no'],
                d['base_net_total'], d['base_grand_total'], d['supplier'], d['taxes_and_charges'],
                d['gstin'], d['state'], d['is_import'], 'Input',
                t['ca'], t['sa'], t['ia']
            ]
            data.append(row)
            
    return data


def get_conditions(filters):
    si_cond = ""
    pi_cond = ""

    if filters.get("type") == 'Sales Invoice':
        if filters.get("item_wise") == 1 and filters.get("hsn") == 1:
            frappe.throw("Only one checkbox allowed to be checked at a given time.")

        if filters.get("customer"):
            si_cond += " AND si.customer = '%s'" %filters["customer"]

        if filters.get("from_date"):
            si_cond += " AND si.posting_date >= '%s'" %filters["from_date"]

        if filters.get("to_date"):
            si_cond += " AND si.posting_date <= '%s'" %filters["to_date"]

        if filters.get("letter_head"):
            si_cond += " AND si.letter_head = '%s'" %filters["letter_head"]

        if filters.get("taxes"):
            si_cond += " AND si.taxes_and_charges = '%s'" %filters["taxes"]
    elif filters.get("type") == 'Purchase Invoice':
        if filters.get("item_wise") == 1 or filters.get("hsn") == 1:
            frappe.throw("Uncheck these Filters as they are still not Implemented.")

        if filters.get("supplier"):
            pi_cond += " AND pi.supplier = '%s'" %filters["supplier"]

        if filters.get("from_date"):
            pi_cond += " AND pi.posting_date >= '%s'" %filters["from_date"]

        if filters.get("to_date"):
            pi_cond += " AND pi.posting_date <= '%s'" %filters["to_date"]

        if filters.get("letter_head"):
            pi_cond += " AND pi.letter_head = '%s'" %filters["letter_head"]

        if filters.get("taxes"):
            pi_cond += " AND pi.taxes_and_charges = '%s'" %filters["taxes"]
    return si_cond, pi_cond

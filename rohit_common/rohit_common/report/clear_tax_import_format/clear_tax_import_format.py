# Copyright (c) 2013, Rohit Industries Ltd. and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from datetime import date
from rohit_common.rohit_common.report.rigpl_legacy_gstr1.rigpl_legacy_gstr1 import Gstr1Report
from frappe.utils import flt

def execute(filters=None):
    return ClearTaxImport(filters).run()

class ClearTaxImport(Gstr1Report):
    def __init__(self, filters=None):
        super(ClearTaxImport, self).__init__(filters)
        self.filters = frappe._dict(filters or {})
        self.columns = []
        self.data = []
        self.doctype = filters.get("type")
        
        if filters.get("type") == 'Sales Invoice':
            self.tax_doctype = "Sales Taxes and Charges"
            self.select_columns = """
                name as invoice_number,
                customer,
                posting_date as posting_date_unformatted,
                base_grand_total,
                base_net_total,
                taxes_and_charges,
                COALESCE(NULLIF(customer_gstin,''), NULLIF(billing_address_gstin, '')) as customer_gstin,
                place_of_supply,
                ecommerce_gstin,
                reverse_charge,
                invoice_type,
                return_against,
                is_return,
                export_type,
                port_code,
                shipping_bill_number,
                shipping_bill_date,
                reason_for_issuing_document,
                customer_address
            """
        elif filters.get("type") == 'Purchase Invoice':
            self.tax_doctype = "Purchase Taxes and Charges"
            self.select_columns = """
                name as invoice_number,
                supplier,
                posting_date as posting_date_unformatted,
                bill_date,
                bill_no,
                taxes_and_charges,
                base_grand_total,
                base_net_total,
                supplier_gstin,
                place_of_supply,
                ecommerce_gstin,
                reverse_charge,
                invoice_type,
                return_against,
                is_return,
                export_type,
                reason_for_issuing_document,
                eligibility_for_itc
            """

    def get_data(self):
        # Use self.invoice_items_details if available (from fixed parent), otherwise fallback
        items_source = getattr(self, "invoice_items_details", None)
        if not items_source and hasattr(self, "invoices"):
             items_source = {}

        for inv_name, invoice_details in self.invoices.items():
            items = items_source.get(inv_name, [])
            
            # Group items by rate
            items_by_rate = {}
            for item in items:
                rate = flt(item.igst_rate) + flt(item.cgst_rate) + flt(item.sgst_rate)
                items_by_rate.setdefault(rate, []).append(item)
            
            for rate, rate_items in items_by_rate.items():
                row, taxable_value = self.get_row_data_for_invoice(inv_name, invoice_details, rate, rate_items)
                
                # --- FILTER: Remove rows with no value ---
                # This is the ONLY filter we need. It removes true duplicates/empty rows.
                # We DO NOT filter by rate==0 , so valid 0% items will show.
                if taxable_value <= 0:
                    continue
                # -----------------------------------------

                igst_paid = 0
                cgst_paid = 0
                sgst_paid = 0
                cess_paid = 0
                itc_igst = 0
                itc_cgst = 0
                itc_sgst = 0
                itc_cess = 0
                
                for item in rate_items:
                    igst_paid += flt(item.igst_amount)
                    cgst_paid += flt(item.cgst_amount)
                    sgst_paid += flt(item.sgst_amount)
                    cess_paid += flt(item.cess_amount)
                    
                    if self.doctype == 'Purchase Invoice':
                        itc_igst += flt(item.igst_amount)
                        itc_cgst += flt(item.cgst_amount)
                        itc_sgst += flt(item.sgst_amount)
                        itc_cess += flt(item.cess_amount)

                if self.doctype == 'Purchase Invoice':
                    row += [
                        igst_paid, cgst_paid, sgst_paid, cess_paid,
                        invoice_details.get('eligibility_for_itc') or 'All Other ITC',
                        itc_igst, itc_cgst, itc_sgst, itc_cess
                    ]
                elif self.doctype == 'Sales Invoice':
                    if self.is_igst_invoice(inv_name):
                        row += [igst_paid, 0, 0]
                    else:
                        row += [0, cgst_paid, sgst_paid]
                    row.append(cess_paid)
                
                if self.filters.get("type_of_business") ==  "CDNR":
                    row.append("Y" if invoice_details.posting_date <= date(2017, 7, 1) else "N")
                    row.append("C" if invoice_details.return_against else "R")

                self.data.append(row)
    
    def is_igst_invoice(self, inv_name):
        # Check if invoice is in the IGST list (populated by parent)
        return hasattr(self, "igst_invoices") and inv_name in self.igst_invoices

    def get_columns(self):
        tax_val_col = { "fieldname": "taxable_value", "label": "Taxable Value", "fieldtype": "Currency", "width": 100 }
        rate_col = { "fieldname": "rate", "label": "Rate", "fieldtype": "Int", "width": 60 }

        if self.filters.get("type") == 'Sales Invoice':
            self.invoice_columns = [
                { "fieldname": "posting_date_unformatted", "label": "Invoice Date", "fieldtype": "Date", "width": 80 },
                { "fieldname": "invoice_number", "label": "Invoice Number", "fieldtype": "Link", "options": "Sales Invoice", "width": 120 },
                { "fieldname": "base_net_total", "label": "Net Total", "fieldtype": "Currency", "width": 80 },
                { "fieldname": "base_grand_total", "label": "Grand Total", "fieldtype": "Currency", "width": 80 },
                { "fieldname": "customer", "label": "Customer Link", "fieldtype": "Link", "options": "Customer", "width": 200 },
                { "fieldname": "taxes_and_charges", "label": "Tax Link", "fieldtype": "Link", "options": "Sales Taxes and Charges Template", "width": 150 },
                { "fieldname": "customer_gstin", "label": "Customer GSTIN", "fieldtype": "Data", "width": 120 },
                { "fieldname": "place_of_supply", "label": "Place of Supply", "fieldtype": "Data", "width": 120 },
                { "fieldname": "reverse_charge", "label": "Reverse Charge", "fieldtype": "Data", "width": 80 },
                { "fieldname": "invoice_type", "label": "Invoice Type", "fieldtype": "Data", "width": 80 },
                { "fieldname": "ecommerce_gstin", "label": "E-Comm GSTIN", "fieldtype": "Data", "width": 120 },
                { "fieldname": "reason_for_issuing_document", "label": "Reason", "fieldtype": "Data", "width": 120 },
                { "fieldname": "is_export", "label": "Is EXP", "fieldtype": "Data", "width": 30 },
                { "fieldname": "gst_paid_on_export", "label": "GST Paid on EXP", "fieldtype": "Data", "width": 30 },
                { "fieldname": "export_shb_no", "label": "EXP SHB #", "fieldtype": "Data", "width": 30 },
                { "fieldname": "export_shb_date", "label": "EXP SHB Date", "fieldtype": "Data", "width": 30 },
                { "fieldname": "export_destination_country_code", "label": "Exp Dest Country Code", "fieldtype": "Data", "width": 30 },
                { "fieldname": "customer_address", "label": "Billing Address Link", "fieldtype": "Link", "options": "Address", "width": 80 }
            ]
            self.tax_columns = [
                rate_col, tax_val_col,
                { "fieldname": "integrated_tax_paid", "label": "Integrated Tax Paid", "fieldtype": "Currency", "width": 100 },
                { "fieldname": "central_tax_paid", "label": "Central Tax Paid", "fieldtype": "Currency", "width": 100 },
                { "fieldname": "state_tax_paid", "label": "State/UT Tax Paid", "fieldtype": "Currency", "width": 100 },
                { "fieldname": "cess_amount", "label": "Cess Paid", "fieldtype": "Currency", "width": 100 }
            ]
            self.other_columns = []

        elif self.filters.get("type") == 'Purchase Invoice':
            self.invoice_columns = [
                { "fieldname": "invoice_number", "label": "PI #", "fieldtype": "Link", "options": "Purchase Invoice", "width": 120 },
                { "fieldname": "posting_date_unformatted", "label": "PI Posting Date", "fieldtype": "Date", "width": 80 },
                { "fieldname": "bill_date", "label": "Supplier PI Date", "fieldtype": "Date", "width": 80 },
                { "fieldname": "bill_no", "label": "Supplier PI No", "fieldtype": "Data", "width": 80 },
                { "fieldname": "supplier", "label": "Supplier Link", "fieldtype": "Link", "options": "Supplier", "width": 200 },
                { "fieldname": "taxes_and_charges", "label": "Tax Link", "fieldtype": "Link", "options": "Purchase Taxes and Charges Template", "width": 150 },
                { "fieldname": "supplier_gstin", "label": "GSTIN of Supplier", "fieldtype": "Data", "width": 130 },
                { "fieldname": "place_of_supply", "label": "Place of Supply", "fieldtype": "Data", "width": 120 },
                { "fieldname": "invoice_value", "label": "Invoice Value", "fieldtype": "Currency", "width": 120 },
                { "fieldname": "reverse_charge", "label": "Reverse Charge", "fieldtype": "Data", "width": 80 },
                { "fieldname": "invoice_type", "label": "Invoice Type", "fieldtype": "Data", "width": 80 }
            ]
            self.tax_columns = [
                rate_col, tax_val_col,
                { "fieldname": "integrated_tax_paid", "label": "Integrated Tax Paid", "fieldtype": "Currency", "width": 100 },
                { "fieldname": "central_tax_paid", "label": "Central Tax Paid", "fieldtype": "Currency", "width": 100 },
                { "fieldname": "state_tax_paid", "label": "State/UT Tax Paid", "fieldtype": "Currency", "width": 100 },
                { "fieldname": "cess_amount", "label": "Cess Paid", "fieldtype": "Currency", "width": 100 },
                { "fieldname": "eligibility_for_itc", "label": "Eligibility For ITC", "fieldtype": "Data", "width": 100 },
                { "fieldname": "itc_integrated_tax", "label": "Availed ITC Integrated Tax", "fieldtype": "Currency", "width": 100 },
                { "fieldname": "itc_central_tax", "label": "Availed ITC Central Tax", "fieldtype": "Currency", "width": 100 },
                { "fieldname": "itc_state_tax", "label": "Availed ITC State/UT Tax", "fieldtype": "Currency", "width": 100 },
                { "fieldname": "itc_cess_amount", "label": "Availed ITC Cess ", "fieldtype": "Currency", "width": 100 }
            ]
            self.other_columns = []
        
        self.columns = self.invoice_columns + self.tax_columns + self.other_columns
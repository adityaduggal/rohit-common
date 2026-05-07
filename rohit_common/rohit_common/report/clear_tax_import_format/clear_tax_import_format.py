# Copyright (c) 2013, Rohit Industries Ltd. and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe, json
from frappe import _
from frappe.utils import flt, formatdate, getdate
from datetime import date
from rohit_common.rohit_common.report.rigpl_legacy_gstr1.rigpl_legacy_gstr1 import Gstr1Report


def execute(filters=None):
    return ClearTaxImport(filters).run()


class ClearTaxImport(Gstr1Report):
    def __init__(self, filters=None):
        super(ClearTaxImport, self).__init__(filters)
        self.filters = frappe._dict(filters or {})
        self.columns = []
        self.data = []
        self.doctype = self.filters.get("type")
        self.tax_doctype = (
            "Sales Taxes and Charges"
            if self.doctype == "Sales Invoice"
            else "Purchase Taxes and Charges"
        )

        # --- DEFINE COLUMNS / SELECTS ---
        # NOTE: base_net_total included in both doctypes; only used for Sales columns
        if self.doctype == "Sales Invoice":
            self.select_columns = """
                name as invoice_number, customer as customer_name, posting_date,
                base_grand_total, base_rounded_total, base_net_total, taxes_and_charges,
                COALESCE(NULLIF(customer_gstin,''), NULLIF(billing_address_gstin, '')) as customer_gstin,
                place_of_supply, ecommerce_gstin, reverse_charge, invoice_type,
                return_against, is_return, export_type, port_code,
                shipping_bill_number, shipping_bill_date, reason_for_issuing_document,
                customer_address
            """
        elif self.doctype == "Purchase Invoice":
            self.select_columns = """
                name as invoice_number, supplier as customer_name, posting_date,
                bill_date, bill_no, taxes_and_charges,
                base_grand_total, base_rounded_total, base_net_total,
                supplier_gstin as customer_gstin, place_of_supply, ecommerce_gstin,
                reverse_charge, invoice_type, return_against, is_return,
                export_type, reason_for_issuing_document, eligibility_for_itc,
                itc_integrated_tax, itc_central_tax, itc_state_tax, itc_cess_amount
            """

    def run(self):
        self.get_columns()
        self.gst_accounts = self.get_gst_accounts_safe()
        self.get_invoice_data_custom()

        if self.invoices:
            # Fetch items
            self.get_invoice_items_custom()
            # Map items to tax rates
            self.get_items_based_on_tax_rate_custom()
            # Build rows
            self.invoice_fields = [d["fieldname"] for d in self.invoice_columns]
            self.get_data_custom()

        return self.columns, self.data

    # ----------------------------------------------------------------------
    # COMMON: GST Accounts
    # ----------------------------------------------------------------------
    def get_gst_accounts_safe(self):
        accs = frappe._dict(
            {
                "cgst_account": [],
                "sgst_account": [],
                "igst_account": [],
                "cess_account": [],
            }
        )
        gst_type = "Input" if self.doctype == "Purchase Invoice" else "Output"
        try:
            from india_compliance.gst_india.utils import get_gst_accounts_by_type

            res = get_gst_accounts_by_type(self.filters.company, gst_type)
            if res:
                if res.get("cgst_account"):
                    accs.cgst_account = res.get("cgst_account")
                if res.get("sgst_account"):
                    accs.sgst_account = res.get("sgst_account")
                if res.get("igst_account"):
                    accs.igst_account = res.get("igst_account")
                if res.get("cess_account"):
                    accs.cess_account = res.get("cess_account")
        except ImportError:
            pass

        # Ensure all are lists
        for key in accs:
            if not isinstance(accs[key], list):
                accs[key] = [accs[key]] if accs[key] else []

        return accs

    # ----------------------------------------------------------------------
    # COLUMNS
    # ----------------------------------------------------------------------
    def get_columns(self):
        tax_val_col = {
            "fieldname": "taxable_value",
            "label": "Taxable Value",
            "fieldtype": "Currency",
            "width": 100,
        }
        rate_col = {"fieldname": "rate", "label": "Rate", "fieldtype": "Int", "width": 60}

        self.tax_columns = [
            rate_col,
            tax_val_col,
            {
                "fieldname": "integrated_tax_paid",
                "label": "Integrated Tax Paid",
                "fieldtype": "Currency",
                "width": 100,
            },
            {
                "fieldname": "central_tax_paid",
                "label": "Central Tax Paid",
                "fieldtype": "Currency",
                "width": 100,
            },
            {
                "fieldname": "state_tax_paid",
                "label": "State/UT Tax Paid",
                "fieldtype": "Currency",
                "width": 100,
            },
            {
                "fieldname": "cess_amount",
                "label": "Cess Paid",
                "fieldtype": "Currency",
                "width": 100,
            },
        ]

        # --- SALES COLUMNS ---
        if self.doctype == "Sales Invoice":
            self.invoice_columns = [
                {
                    "fieldname": "posting_date",
                    "label": "Invoice Date",
                    "fieldtype": "Date",
                    "width": 80,
                },
                {
                    "fieldname": "invoice_number",
                    "label": "Invoice Number",
                    "fieldtype": "Link",
                    "options": "Sales Invoice",
                    "width": 120,
                },
                {
                    "fieldname": "base_net_total",
                    "label": "Net Total",
                    "fieldtype": "Currency",
                    "width": 80,
                },
                {
                    "fieldname": "invoice_value",
                    "label": "Grand Total",
                    "fieldtype": "Currency",
                    "width": 80,
                },
                {
                    "fieldname": "customer_name",
                    "label": "Customer Link",
                    "fieldtype": "Link",
                    "options": "Customer",
                    "width": 200,
                },
                {
                    "fieldname": "taxes_and_charges",
                    "label": "Tax Link",
                    "fieldtype": "Link",
                    "options": "Sales Taxes and Charges Template",
                    "width": 150,
                },
                {
                    "fieldname": "customer_gstin",
                    "label": "Customer GSTIN",
                    "fieldtype": "Data",
                    "width": 120,
                },
                {
                    "fieldname": "place_of_supply",
                    "label": "Place of Supply",
                    "fieldtype": "Data",
                    "width": 120,
                },
                {
                    "fieldname": "reverse_charge",
                    "label": "Reverse Charge",
                    "fieldtype": "Data",
                    "width": 80,
                },
                {
                    "fieldname": "invoice_type",
                    "label": "Invoice Type",
                    "fieldtype": "Data",
                    "width": 80,
                },
                {
                    "fieldname": "ecommerce_gstin",
                    "label": "E-Comm GSTIN",
                    "fieldtype": "Data",
                    "width": 120,
                },
                {
                    "fieldname": "reason_for_issuing_document",
                    "label": "Reason",
                    "fieldtype": "Data",
                    "width": 120,
                },
                {
                    "fieldname": "is_export",
                    "label": "Is EXP",
                    "fieldtype": "Data",
                    "width": 30,
                },
                {
                    "fieldname": "gst_paid_on_export",
                    "label": "GST Paid on EXP",
                    "fieldtype": "Data",
                    "width": 30,
                },
                {
                    "fieldname": "export_shb_no",
                    "label": "EXP SHB #",
                    "fieldtype": "Data",
                    "width": 30,
                },
                {
                    "fieldname": "export_shb_date",
                    "label": "EXP SHB Date",
                    "fieldtype": "Data",
                    "width": 30,
                },
                {
                    "fieldname": "export_destination_country_code",
                    "label": "Exp Dest Country Code",
                    "fieldtype": "Data",
                    "width": 30,
                },
                {
                    "fieldname": "customer_address",
                    "label": "Billing Address Link",
                    "fieldtype": "Link",
                    "options": "Address",
                    "width": 80,
                },
            ]
            self.other_columns = []

        # --- PURCHASE COLUMNS ---
        elif self.doctype == "Purchase Invoice":
            self.invoice_columns = [
                {
                    "fieldname": "invoice_number",
                    "label": "PI #",
                    "fieldtype": "Link",
                    "options": "Purchase Invoice",
                    "width": 120,
                },
                {
                    "fieldname": "posting_date",
                    "label": "PI Posting Date",
                    "fieldtype": "Date",
                    "width": 80,
                },
                {
                    "fieldname": "bill_date",
                    "label": "Supplier PI Date",
                    "fieldtype": "Date",
                    "width": 80,
                },
                {
                    "fieldname": "bill_no",
                    "label": "Supplier PI No",
                    "fieldtype": "Data",
                    "width": 80,
                },
                {
                    "fieldname": "customer_name",
                    "label": "Supplier Link",
                    "fieldtype": "Link",
                    "options": "Supplier",
                    "width": 200,
                },
                {
                    "fieldname": "taxes_and_charges",
                    "label": "Tax Link",
                    "fieldtype": "Link",
                    "options": "Purchase Taxes and Charges Template",
                    "width": 150,
                },
                {
                    "fieldname": "customer_gstin",
                    "label": "GSTIN of Supplier",
                    "fieldtype": "Data",
                    "width": 130,
                },
                {
                    "fieldname": "place_of_supply",
                    "label": "Place of Supply",
                    "fieldtype": "Data",
                    "width": 120,
                },
                {
                    "fieldname": "invoice_value",
                    "label": "Invoice Value",
                    "fieldtype": "Currency",
                    "width": 120,
                },
                {
                    "fieldname": "reverse_charge",
                    "label": "Reverse Charge",
                    "fieldtype": "Data",
                    "width": 80,
                },
                {
                    "fieldname": "invoice_type",
                    "label": "Invoice Type",
                    "fieldtype": "Data",
                    "width": 80,
                },
            ]
            self.other_columns = [
                {
                    "fieldname": "eligibility_for_itc",
                    "label": "Eligibility For ITC",
                    "fieldtype": "Data",
                    "width": 100,
                },
                {
                    "fieldname": "itc_integrated_tax",
                    "label": "Availed ITC Integrated Tax",
                    "fieldtype": "Currency",
                    "width": 100,
                },
                {
                    "fieldname": "itc_central_tax",
                    "label": "Availed ITC Central Tax",
                    "fieldtype": "Currency",
                    "width": 100,
                },
                {
                    "fieldname": "itc_state_tax",
                    "label": "Availed ITC State/UT Tax",
                    "fieldtype": "Currency",
                    "width": 100,
                },
                {
                    "fieldname": "itc_cess_amount",
                    "label": "Availed ITC Cess ",
                    "fieldtype": "Currency",
                    "width": 100,
                },
            ]

        self.columns = self.invoice_columns + self.tax_columns + self.other_columns

    # ----------------------------------------------------------------------
    # INVOICE DATA
    # ----------------------------------------------------------------------
    def get_invoice_data_custom(self):
        self.invoices = frappe._dict()
        conditions = ""

        # Common filters
        if self.filters.get("letter_head"):
            conditions += " AND letter_head = '%s'" % (self.filters.get("letter_head"))
        if self.filters.get("company"):
            conditions += " and company=%(company)s"
        if self.filters.get("from_date"):
            conditions += " and posting_date>=%(from_date)s"
        if self.filters.get("to_date"):
            conditions += " and posting_date<=%(to_date)s"

        # Sales-specific type_of_business filters
        if self.doctype == "Sales Invoice":
            if self.filters.get("type_of_business") == "B2B":
                conditions += (
                    " and ifnull(invoice_type, '') != 'Export' and is_return != 1 "
                )
            elif self.filters.get("type_of_business") == "CDNR":
                conditions += " and is_return = 1 "

        invoice_data = frappe.db.sql(
            """
            select {select_columns} from `tab{doctype}`
            where docstatus = 1 {where_conditions} and is_opening = 'No'
            order by posting_date desc
            """.format(
                select_columns=self.select_columns,
                doctype=self.doctype,
                where_conditions=conditions,
            ),
            self.filters,
            as_dict=1,
        )

        for d in invoice_data:
            self.invoices.setdefault(d.invoice_number, d)

    # ----------------------------------------------------------------------
    # INVOICE ITEMS (doctype-specific)
    # ----------------------------------------------------------------------
    def get_invoice_items_custom(self):
        if not self.invoices:
            return

        # --- SALES: simple dict parent -> {item_key: taxable_value} ---
        if self.doctype == "Sales Invoice":
            self.invoice_items = frappe._dict()
            items = frappe.db.sql(
                """
                select item_code, item_name, parent, taxable_value, base_net_amount
                from `tab%s Item` where parent in (%s)
            """
                % (
                    self.doctype,
                    ", ".join(["%s"] * len(self.invoices)),
                ),
                tuple(self.invoices),
                as_dict=1,
            )

            for d in items:
                if d.parent not in self.invoice_items:
                    self.invoice_items[d.parent] = {}
                key = d.item_code or d.item_name
                if not key:
                    continue
                val = flt(d.taxable_value) or flt(d.base_net_amount)
                current_val = self.invoice_items[d.parent].get(key, 0.0)
                self.invoice_items[d.parent][key] = current_val + val

        # --- PURCHASE: list with rate info (to avoid double counting) ---
        else:
            self.invoice_items = frappe._dict()
            items = frappe.db.sql(
                """
                select item_code, item_name, parent, taxable_value, base_net_amount,
                       igst_rate, cgst_rate, sgst_rate
                from `tab%s Item` where parent in (%s)
            """
                % (
                    self.doctype,
                    ", ".join(["%s"] * len(self.invoices)),
                ),
                tuple(self.invoices),
                as_dict=1,
            )

            for d in items:
                if d.parent not in self.invoice_items:
                    self.invoice_items[d.parent] = []

                key = d.item_code or d.item_name
                if not key:
                    continue

                val = flt(d.taxable_value) or flt(d.base_net_amount)
                rate = flt(d.igst_rate) + flt(d.cgst_rate) + flt(d.sgst_rate)

                self.invoice_items[d.parent].append(
                    {"key": key, "value": val, "item_rate": rate}
                )

    # ----------------------------------------------------------------------
    # TAX DETAILS → items_based_on_tax_rate
    # ----------------------------------------------------------------------
    def get_items_based_on_tax_rate_custom(self):
        if not self.invoices:
            return

        # Pre-cache GST accounts into distinct sets for O(1) lookups
        cgst_sgst_accs = set(
            self.gst_accounts.get("cgst_account", []) + 
            self.gst_accounts.get("sgst_account", [])
        )
        igst_accs = set(self.gst_accounts.get("igst_account", []))
        cess_accs = set(self.gst_accounts.get("cess_account", []))

        tax_details = frappe.db.sql("""
            select parent, account_head, item_wise_tax_detail, base_tax_amount_after_discount_amount
            from `tab%s` where parenttype = %%s and docstatus = 1 and parent in (%s)
            order by account_head
        """ % (self.tax_doctype, ", ".join(["%s"] * len(self.invoices))),
        tuple([self.doctype] + list(self.invoices.keys())), as_dict=1)

        self.items_based_on_tax_rate = {}
        self.invoice_cess = frappe._dict()
        self.cgst_sgst_invoices = set()

        # Optimize JSON parsing by caching
        json_load = json.loads

        for d in tax_details:
            parent, account = d.parent, d.account_head
            
            # Handle Cess separately
            if account in cess_accs:
                self.invoice_cess[parent] = self.invoice_cess.get(parent, 0.0) + flt(d.base_tax_amount_after_discount_amount)
                continue

            # Strict GST Account check
            is_cgst_sgst = False
            acct_lower = account.lower()
            
            if account in cgst_sgst_accs or "cgst" in acct_lower or "sgst" in acct_lower:
                is_cgst_sgst = True
            elif account in igst_accs or "igst" in acct_lower:
                pass
            else:
                # Non-GST tax row → ignore
                continue

            if d.item_wise_tax_detail:
                try:
                    detail = json_load(d.item_wise_tax_detail)
                    for item_key, tax_amounts in detail.items():
                        if isinstance(tax_amounts, dict):
                            tax_rate = flt(tax_amounts.get("tax_rate") or tax_amounts.get("rate") or 0)
                        elif isinstance(tax_amounts, (list, tuple)):
                            tax_rate = flt(tax_amounts[0])
                        else:
                            tax_rate = 0.0

                        if tax_rate > 0:
                            if is_cgst_sgst:
                                tax_rate *= 2
                                self.cgst_sgst_invoices.add(parent)

                            self.items_based_on_tax_rate.setdefault(parent, {}).setdefault(tax_rate, set()).add(item_key)
                except (ValueError, TypeError):
                    pass

        # Add 0-rated invoices
        if hasattr(self, "invoice_items"):
            for inv, items in self.invoice_items.items():
                if inv not in self.items_based_on_tax_rate:
                    if self.doctype == "Sales Invoice":
                        self.items_based_on_tax_rate.setdefault(inv, {})[0.0] = set(items.keys())
                    else:
                        self.items_based_on_tax_rate.setdefault(inv, {})[0.0] = {x["key"] for x in items}

    # ----------------------------------------------------------------------
    # DATA BUILD
    # ----------------------------------------------------------------------
    def get_data_custom(self):
        is_sales = self.doctype == "Sales Invoice"
        
        for inv, items_based_on_rate in self.items_based_on_tax_rate.items():
            if is_sales:
                self._append_row(inv, items_based_on_rate)
            else:
                invoice_details = self.invoices.get(inv)
                if not invoice_details: continue
                
                is_return = flt(invoice_details.get("is_return")) == 1 or invoice_details.get("return_against")
                inv_items = self.invoice_items.get(inv, [])
                
                for rate, item_keys in items_based_on_rate.items():
                    # Optimization: Filter items once per rate
                    filtered_taxable = sum(
                        item["value"] for item in inv_items 
                        if item["key"] in item_keys and (abs(item["item_rate"] - rate) < 0.1 or (rate == 0 and item["item_rate"] == 0))
                    )

                    if filtered_taxable == 0 and any(x["item_rate"] != 0 for x in inv_items):
                        continue

                    row = self._build_invoice_base_row(invoice_details, is_return)
                    
                    tax_amount = filtered_taxable * rate / 100.0
                    val_fmt = lambda v: abs(flt(v)) if is_return else flt(v)
                    
                    row += [rate, val_fmt(filtered_taxable)]
                    
                    if inv in self.cgst_sgst_invoices:
                        row += [0.0, val_fmt(tax_amount / 2.0), val_fmt(tax_amount / 2.0)]
                    else:
                        row += [val_fmt(tax_amount), 0.0, 0.0]

                    row += [val_fmt(self.invoice_cess.get(inv, 0.0))]
                    
                    # Purchase ITC Columns
                    row += [
                        invoice_details.get("eligibility_for_itc") or "All Other ITC",
                        invoice_details.get("itc_integrated_tax"),
                        invoice_details.get("itc_central_tax"),
                        invoice_details.get("itc_state_tax"),
                        invoice_details.get("itc_cess_amount"),
                    ]
                    
                    if self.filters.get("type_of_business") == "CDNR":
                        row += ["Y" if getdate(invoice_details.posting_date) <= date(2017, 7, 1) else "N",
                                "C" if invoice_details.return_against else "R"]

                    self.data.append(row)

    def _build_invoice_base_row(self, details, is_return):
        row = []
        for fieldname in self.invoice_fields:
            if fieldname == "invoice_value":
                row.append(flt(details.base_rounded_total or details.base_grand_total))
            elif fieldname in ("posting_date", "bill_date", "shipping_bill_date"):
                val = details.get(fieldname)
                row.append(formatdate(val, "dd-MMM-YY") if val else None)
            elif fieldname == "export_type":
                row.append("WPAY" if details.get(fieldname) == "With Payment of Tax" else "WOPAY")
            else:
                row.append(details.get(fieldname))
        return row

    # ----------------------------------------------------------------------
    # SALES helper (unchanged from your Sales working version)
    # ----------------------------------------------------------------------
    def _append_row(self, inv, items_based_on_rate):
        invoice_details = self.invoices.get(inv)

        # Sort rates in ascending order
        for rate in sorted(items_based_on_rate.keys()):
            items = items_based_on_rate[rate]

            # Hide 0-rate if taxable rate exists (except export/exempt cases)
            if rate == 0 and len(items_based_on_rate) > 1:
                is_export = (
                    invoice_details.get("invoice_type") == "Export"
                    or invoice_details.get("export_type")
                    in ["With Payment of Tax", "Without Payment of Tax"]
                )
                if not is_export:
                    continue

            row = []

            is_return = (
                flt(invoice_details.get("is_return")) == 1
                or invoice_details.get("return_against")
            )

            def val_format(v):
                return abs(flt(v)) if is_return else flt(v)

            # invoice-level fields
            for fieldname in self.invoice_fields:
                if fieldname == "invoice_value":
                    val = (
                        invoice_details.base_rounded_total
                        or invoice_details.base_grand_total
                    )
                    row.append(flt(val))  # keep negative sign for returns
                elif fieldname == "base_net_total":
                    val = invoice_details.base_net_total
                    if val is None:
                        val = 0
                    row.append(flt(val))
                elif fieldname in ("posting_date", "bill_date", "shipping_bill_date"):
                    val = invoice_details.get(fieldname)
                    row.append(formatdate(val, "dd-MMM-YY") if val else None)
                elif fieldname == "export_type":
                    val = (
                        "WPAY"
                        if invoice_details.get(fieldname) == "With Payment of Tax"
                        else "WOPAY"
                    )
                    row.append(val)
                elif fieldname == "invoice_number":
                    row.append(invoice_details.get(fieldname))
                elif fieldname == "customer_name":
                    row.append(invoice_details.get(fieldname))
                else:
                    row.append(invoice_details.get(fieldname))

            # Taxable value from items
            taxable_value = 0.0
            inv_items = self.invoice_items.get(inv, {})
            for item_key in items:
                taxable_value += inv_items.get(item_key, 0.0)

            tax_amount = taxable_value * rate / 100.0

            row += [rate, val_format(taxable_value)]

            if inv in self.cgst_sgst_invoices:
                row += [
                    0.0,
                    val_format(tax_amount / 2.0),
                    val_format(tax_amount / 2.0),
                ]
            else:
                row += [val_format(tax_amount), 0.0, 0.0]

            row += [val_format(self.invoice_cess.get(inv, 0.0))]

            # Purchase-only ITC columns do NOT apply here

            # Sales CDNR flags
            if self.filters.get("type_of_business") == "CDNR":
                row.append(
                    "Y"
                    if getdate(invoice_details.posting_date) <= date(2017, 7, 1)
                    else "N"
                )
                row.append("C" if invoice_details.return_against else "R")

            self.data.append(row)
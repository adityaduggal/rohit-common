import frappe

def set_einvoice_log_status_in_sales_invoice(doc, method=None):
    """
    Set e-invoice status in Sales Invoice based on e-Invoice Log changes
    """
    if doc.reference_doctype == "Sales Invoice" and doc.reference_name:
        frappe.db.set_value("Sales Invoice", doc.reference_name, "einvoice_status", "Generated")
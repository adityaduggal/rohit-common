import io
import re
import json
import frappe
from pyqrcode import create as qrcreate
from frappe.utils import get_datetime

def set_einvoice_log_status_in_sales_invoice(doc, method=None):
    """
    Set e-invoice status in Sales Invoice based on e-Invoice Log changes
    """
    if doc.reference_doctype == "Sales Invoice" and doc.reference_name:
        frappe.db.set_value("Sales Invoice", doc.reference_name, "einvoice_status", "Generated")

def attach_qr_to_invoice(reference_doctype, reference_name, qr_value):
    """Create a File doc for QR and attach to Sales Invoice.qrcode_image field."""
    if not qr_value:
        return None

    # sanitize filename
    new_name = re.sub('[^A-Za-z0-9]+', '', reference_name)
    filename = f"QRCode_{new_name}.png"

    qr_image = io.BytesIO()
    url = qrcreate(qr_value, error='L')
    # scale can be adjusted; quiet_zone=1 keeps small whitespace
    url.png(qr_image, scale=2, quiet_zone=1)

    file_doc = frappe.get_doc({
        "doctype": "File",
        "file_name": filename,
        "attached_to_doctype": reference_doctype,
        "attached_to_name": reference_name,
        "attached_to_field": "qrcode_image",
        "is_private": 1,
        "content": qr_image.getvalue()
    })
    file_doc.insert(ignore_permissions=True)
    # set qrcode_image field value as file URL
    frappe.db.set_value(reference_doctype, reference_name, "qrcode_image", file_doc.file_url)
    frappe.db.commit()
    return file_doc.file_url

def sync_einvoice_log_to_reference(doc, method=None):
    """
    doc = e-Invoice Log document (india_compliance's doctype name may be exactly 'e-Invoice Log')
    This will update the Sales Invoice (or other reference_doctype) with IRN, AckNo, AckDt and attach QR image.
    """
    ref_doctype = getattr(doc, "reference_doctype", None)
    ref_name = getattr(doc, "reference_name", None)
    if not (ref_doctype and ref_name):
        return

    try:
        if getattr(doc, "irn", None):
            frappe.db.set_value(ref_doctype, ref_name, "irn", doc.irn)

        if getattr(doc, "acknowledgement_number", None):
            frappe.db.set_value(ref_doctype, ref_name, "ack_no", doc.acknowledgement_number)

        if getattr(doc, "acknowledged_on", None):
            ack_dt = get_datetime(doc.acknowledged_on) if isinstance(doc.acknowledged_on, str) else doc.acknowledged_on
            frappe.db.set_value(ref_doctype, ref_name, "ack_date", ack_dt)

        # Attach QR — try doc.signed_qr_code first, otherwise check invoice_data JSON for SignedQRCode
        qr_value = getattr(doc, "signed_qr_code", None)
        if not qr_value:
            invoice_data = getattr(doc, "invoice_data", None)
            if invoice_data:
                try:
                    inv_json = json.loads(invoice_data) if isinstance(invoice_data, str) else invoice_data
                    # common places: SignedQRCode or SignedQRCode (case-sensitive may vary)
                    qr_value = inv_json.get("SignedQRCode") or inv_json.get("signed_qr_code") or inv_json.get("signedQrCode")
                except Exception:
                    qr_value = None

        if qr_value:
            attach_qr_to_invoice(ref_doctype, ref_name, qr_value)

    except Exception as e:
        frappe.log_error(message=frappe.get_traceback(), title="sync_einvoice_log_to_reference failed")
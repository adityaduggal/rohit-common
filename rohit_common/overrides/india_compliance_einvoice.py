import frappe
from collections import defaultdict
from india_compliance.gst_india.utils.e_invoice import EInvoiceData

original_get_data = EInvoiceData.get_data

def custom_get_data(self):
    frappe.log_error("Custom get_data called", "EInvoice Patch")
    data = original_get_data(self)

    # Summarize ItemList by HSN
    summarized = defaultdict(lambda: {
        "HsnCd": "",
        "IsServc": "N",
        "GstRt": 0,
        "AssAmt": 0.0,
        "CgstAmt": 0.0,
        "SgstAmt": 0.0,
        "IgstAmt": 0.0,
        "CesAmt": 0.0,
        "TotItemVal": 0.0
    })

    for item in data.get("ItemList", []):
        hsn = item.get("HsnCd")
        s = summarized[hsn]

        if not s["HsnCd"]:
            s["HsnCd"] = hsn
            s["IsServc"] = item.get("IsServc", "N")
            s["GstRt"] = item.get("GstRt", 0)

        for k in ["AssAmt","CgstAmt","SgstAmt","IgstAmt","CesAmt","TotItemVal"]:
            s[k] += item.get(k, 0.0)

    new_items = []
    for i, (hsn, vals) in enumerate(summarized.items(), 1):
        vals["SlNo"] = str(i)
        vals["PrdDesc"] = f"Goods with HSN {hsn}"
        vals["Qty"] = 1.0
        vals["Unit"] = "OTH"
        vals["UnitPrice"] = vals["AssAmt"]
        vals["TotAmt"] = vals["AssAmt"]
        new_items.append(vals)

    data["ItemList"] = new_items
    return data
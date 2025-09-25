__version__ = "15.0.0"

# Monkey-patch AssetDepreciationSchedule to add set_draft_asset_depr_schedule_details

from erpnext.assets.doctype.asset_depreciation_schedule.asset_depreciation_schedule import AssetDepreciationSchedule
import frappe
from rohit_common.patches.asset_depr_schedule_patch_utils import set_draft_asset_depr_schedule_details
AssetDepreciationSchedule.set_draft_asset_depr_schedule_details = set_draft_asset_depr_schedule_details

# Monkey-patched File to allow System Manager to access all files

from rohit_common.overrides.file import get_permission_query_conditions,has_permission
frappe.frappe.core.doctype.file.file.has_permission=has_permission
frappe.frappe.core.doctype.file.file.get_permission_query_conditions=get_permission_query_conditions

# Override for EInvoiceData.get_data
# from india_compliance.gst_india.utils.e_invoice import EInvoiceData
# from rohit_common.overrides.india_compliance_einvoice import custom_get_data
# EInvoiceData.get_data = custom_get_data

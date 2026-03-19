import frappe

def run_unwanted_patches():
	if not frappe.db.exists("Patch Log", {"patch": "frappe.patches.v16.running_unwanted_patches"}):
		#frappe
		set_route_for_blog_category()
		set_read_times()
		update_icons_in_customized_desk_pages()
		rename_desk_page_to_workspace()
		setup_likes_from_feedback()
        # skip_notification_channel_patch()
        # skip_update_reports_with_range()

		#erpnext
		update_is_cancelled_field()
		change_is_subcontracted_fieldtype()
		rename_account_type_doctype()
		execute_rename_desk_page()
		replace_pos_page_with_point_of_sale_page()
		print_uom_after_quantity_patch()
		update_member_email_address()
		clear_reconciliation_values_from_singles()
		execute_rename_tds_report()
		
		running_unwanted_patches()
def running_unwanted_patches():
	frappe.get_doc({
		'doctype': 'Patch Log',
		'patch': 'frappe.patches.v16.running_unwanted_patches',
	}).insert(ignore_permissions=True)
	frappe.db.commit()
def setup_likes_from_feedback():
	frappe.get_doc({
		'doctype': 'Patch Log',
		'patch': 'frappe.patches.v14_0.setup_likes_from_feedback',
	}).insert(ignore_permissions=True)
	frappe.db.commit()
 
def rename_desk_page_to_workspace():
	frappe.get_doc({
		'doctype': 'Patch Log',
		'patch': 'frappe.patches.v13_0.rename_desk_page_to_workspace # 02.02.2021',
	}).insert(ignore_permissions=True)
	frappe.db.commit()
def update_icons_in_customized_desk_pages():
	frappe.get_doc({
		'doctype': 'Patch Log',
		'patch': 'frappe.patches.v13_0.update_icons_in_customized_desk_pages',
	}).insert(ignore_permissions=True)
	frappe.db.commit()

def set_route_for_blog_category():
	frappe.get_doc({
		'doctype': 'Patch Log',
		'patch': 'frappe.patches.v13_0.set_route_for_blog_category',
	}).insert(ignore_permissions=True)
	frappe.db.commit()

def set_read_times():
	frappe.get_doc({
		'doctype': 'Patch Log',
		'patch': 'frappe.patches.v13_0.set_read_times',
	}).insert(ignore_permissions=True)
	frappe.db.commit()
def update_is_cancelled_field():
    frappe.get_doc({
		'doctype': 'Patch Log',
		'patch': 'erpnext.patches.v12_0.update_is_cancelled_field',
	}).insert(ignore_permissions=True)
    frappe.db.commit()
def change_is_subcontracted_fieldtype():
    frappe.get_doc({
		'doctype': 'Patch Log',
		'patch': 'erpnext.patches.v14_0.change_is_subcontracted_fieldtype',
	}).insert(ignore_permissions=True)
    frappe.db.commit()
def rename_account_type_doctype():
    frappe.get_doc({
		'doctype': 'Patch Log',
		'patch': 'erpnext.patches.v12_0.rename_account_type_doctype',
	}).insert(ignore_permissions=True)
    frappe.db.commit()
    
def execute_rename_desk_page():
	frappe.get_doc({
		'doctype': 'Patch Log',
		'patch': 'execute:frappe.rename_doc("Desk Page", "Getting Started", "Home", force=True)',
	}).insert(ignore_permissions=True)
	frappe.db.commit()
 
def replace_pos_page_with_point_of_sale_page():
	frappe.get_doc({
		'doctype': 'Patch Log',
		'patch': 'erpnext.patches.v13_0.replace_pos_page_with_point_of_sale_page',
	}).insert(ignore_permissions=True)
	frappe.db.commit()
 
def print_uom_after_quantity_patch():
	frappe.get_doc({
		'doctype': 'Patch Log',
		'patch': 'erpnext.patches.v13_0.print_uom_after_quantity_patch',
	}).insert(ignore_permissions=True)
	frappe.db.commit()
def update_member_email_address():
	frappe.get_doc({
		'doctype': 'Patch Log',
		'patch': 'erpnext.patches.v13_0.update_member_email_address',
	}).insert(ignore_permissions=True)
	frappe.db.commit()
def clear_reconciliation_values_from_singles():
	frappe.get_doc({
		'doctype': 'Patch Log',
		'patch': 'erpnext.patches.v14_0.clear_reconciliation_values_from_singles',
	}).insert(ignore_permissions=True)
	frappe.db.commit()
def execute_rename_tds_report():
	frappe.get_doc({
		'doctype': 'Patch Log',
		'patch': 'execute:frappe.rename_doc("Report", "TDS Payable Monthly", "Tax Withholding Details", force=True)',
	}).insert(ignore_permissions=True)
	frappe.db.commit()
# def skip_notification_channel_patch():
#     if not frappe.db.exists("Patch Log", {"patch": "frappe.patches.v13_0.update_notification_channel_if_empty"}):
#         frappe.get_doc({
#             "doctype": "Patch Log",
#             "patch": "frappe.patches.v13_0.update_notification_channel_if_empty",
#         }).insert(ignore_permissions=True)
#         frappe.db.commit()


# def skip_update_reports_with_range():
#     if not frappe.db.exists("Patch Log", {"patch": "erpnext.patches.v14_0.update_reports_with_range"}):
#         frappe.get_doc({
#             "doctype": "Patch Log",
#             "patch": "erpnext.patches.v14_0.update_reports_with_range",
#         }).insert(ignore_permissions=True)
#         frappe.db.commit()
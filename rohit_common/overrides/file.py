import frappe
from frappe.permissions import SYSTEM_USER_ROLE, get_doctypes_with_read
from rohit_common.utils.rohit_common_utils import check_system_manager

def has_permission(doc, ptype=None, user=None, debug=False):
	user = user or frappe.session.user

	if user == "Administrator" or check_system_manager(user):
		return True

	if not doc.is_private and ptype in ("read", "select"):
		return True

	if user != "Guest" and doc.owner == user:
		return True

	if doc.attached_to_doctype and doc.attached_to_name:
		attached_to_doctype = doc.attached_to_doctype
		attached_to_name = doc.attached_to_name

		try:
			ref_doc = frappe.get_doc(attached_to_doctype, attached_to_name)
		except ModuleNotFoundError:
			return False
		except frappe.DoesNotExistError:
			frappe.clear_last_message()
			return False

		if ptype in ["write", "create", "delete"]:
			return ref_doc.has_permission("write", debug=debug, user=user)
		else:
			return ref_doc.has_permission("read", debug=debug, user=user)

	return False


def get_permission_query_conditions(user: str | None = None) -> str:
	user = user or frappe.session.user
	if user == "Administrator" or check_system_manager(user):
		return ""

	if SYSTEM_USER_ROLE not in frappe.get_roles(user):
		return f""" `tabFile`.`owner` = {frappe.db.escape(user)} """

	readable_doctypes = ", ".join(repr(dt) for dt in get_doctypes_with_read())
	return f"""
		(`tabFile`.`is_private` = 0)
		OR (`tabFile`.`attached_to_doctype` IS NULL AND `tabFile`.`owner` = {frappe.db.escape(user)})
		OR (`tabFile`.`attached_to_doctype` IN ({readable_doctypes}))
	"""
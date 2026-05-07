import frappe


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def custom_contact_query(doctype, txt, searchfield, start, page_len, filters):
	from frappe.desk.reportview import get_match_cond

	doctype = "Contact"
	if not frappe.get_meta(doctype).get_field(searchfield) and searchfield not in frappe.db.DEFAULT_COLUMNS:
		return []

	link_doctype = filters.pop("link_doctype")
	link_name = filters.pop("link_name")

	# --- START OF DYNAMIC CHANGES ---

	# 1. Get the "Contact" DocType's metadata
	meta = frappe.get_meta("Contact")

	# 2. Get the 'search_fields' string (e.g., "first_name, last_name, email_id")
	search_fields_string = meta.search_fields

	# 3. Create a list, falling back to 'name' and 'full_name' if empty
	if search_fields_string:
		search_fields_list = [field.strip() for field in search_fields_string.split(",")]
	else:
		search_fields_list = ["name", "full_name"]  # default

	# 4. Clean the list: remove empty strings just in case (e.g., "field1,,field2")
	search_fields_list = [f for f in search_fields_list if f]

	# 5. Build the OR conditions dynamically
	search_conditions = " OR ".join(
		[f"`tabContact`.`{field}` like %(txt)s" for field in search_fields_list]
	)

	# --- END OF DYNAMIC CHANGES ---

	return frappe.db.sql(
		f"""select
			`tabContact`.name, `tabContact`.full_name, `tabContact`.company_name,
			`tabContact`.email_id, `tabContact`.phone, `tabContact`.mobile_no
		from
			`tabContact`, `tabDynamic Link`
		where
			`tabDynamic Link`.parent = `tabContact`.name and
			`tabDynamic Link`.parenttype = 'Contact' and
			`tabDynamic Link`.link_doctype = %(link_doctype)s and
			`tabDynamic Link`.link_name = %(link_name)s and
			({search_conditions})
			{get_match_cond(doctype)}
		order by
			if(locate(%(_txt)s, `tabContact`.full_name), locate(%(_txt)s, `tabContact`.company_name), 99999),
			`tabContact`.idx desc, `tabContact`.full_name
		limit %(start)s, %(page_len)s """,
		{
			"txt": "%" + txt + "%",
			"_txt": txt.replace("%", ""),
			"start": start,
			"page_len": page_len,
			"link_name": link_name,
			"link_doctype": link_doctype,
		},
	)
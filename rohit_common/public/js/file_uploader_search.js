// Copyright (c) 2026 Rohit Industries Group Private Limited and Contributors.
// For license information, please see license.txt
//
// The core "Attach File" dialog's folder browser hardcodes the search box
// placeholder to "Search by filename or extension". Server-side, this app
// (rohit_common.core.file.get_files_by_search_text, wired via
// override_whitelisted_methods) already extends the actual search to also
// match any fields listed in the File DocType's "Search Fields" (Customize
// Form). This keeps the placeholder text in sync with that configuration so
// users know which fields they can search by.

frappe.provide("rohit_common.file_uploader");

rohit_common.file_uploader.get_search_placeholder = function (callback) {
	frappe.model.with_doctype("File", function () {
		let meta = frappe.get_meta("File");
		let search_fields = (meta.search_fields || "")
			.split(",")
			.map((f) => f.trim())
			.filter(Boolean);

		let labels = [];
		let seen = new Set();
		search_fields.forEach(function (fieldname) {
			let df = frappe.meta.get_docfield("File", fieldname);
			let label = (df && df.label) || frappe.model.unscrub(fieldname);
			let key = label.toLowerCase();
			if (!seen.has(key)) {
				seen.add(key);
				labels.push(label);
			}
		});

		let text = labels.length
			? __("Search by {0}", [labels.join(", ")])
			: __("Search by filename or extension");
		callback(text);
	});
};

rohit_common.file_uploader.update_search_placeholder = function () {
	let $input = $(".file-filter input[type='search']");
	if (!$input.length) return;
	rohit_common.file_uploader.get_search_placeholder(function (text) {
		$input.attr("placeholder", text);
	});
};

$(document).on("shown.bs.modal", function () {
	// Vue mounts the file browser synchronously on dialog construction, but
	// give it a tick in case the modal-shown event races the render.
	setTimeout(rohit_common.file_uploader.update_search_placeholder, 0);
});

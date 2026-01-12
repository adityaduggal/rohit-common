// Copyright (c) 2022, Rohit Industries Ltd. and contributors
// For license information, please see license.txt

frappe.query_reports["Address Book RIGPL"] = {
	"filters": [
		{
			"fieldname":"type",
			"label": "Address or Contact",
			"fieldtype": "Link",
			"options": "DocType",
			"reqd": 1,
			"get_query": function() {
				return {
					"filters": {
						"name": ["in", "Address, Contact"],
					}
				}
			}
		},
		{
            "fieldname": "link_type",
            "label": "Linked to",
            "fieldtype": "Link",
            "options": "DocType",
            "reqd": 0,
            "get_query": function() {
                let type = frappe.query_report.get_filter_value('type');
                let target_field = "";

                if (type === "Address") {
                    target_field = "address_html";
                } else if (type === "Contact") {
                    target_field = "contact_html";
                } else {
                    frappe.throw("Please Select Address or Contact based Report");
                }

                return {
                    query: "rohit_common.rohit_common.report.address_book_rigpl.address_book_rigpl.get_doctypes_with_field",
                    filters: {
                        "fieldtype": "HTML",
                        "fieldname": target_field
                    }
                };
            }
        },
		{
			"fieldname":"linked_to",
			"label": "Master Name",
			"fieldtype": "Dynamic Link",
			"options": "DocType",
			"reqd": 0,
			"get_options": function() {
				let link_type = frappe.query_report.get_filter_value('link_type');
				if(!link_type) {
					frappe.throw(__("Please First Select Linked To Type"));
				}
				return link_type;
			}
		},
		{
			"fieldname":"territory",
			"label": "Territory",
			"fieldtype": "Link",
			"reqd": 0,
			"get_options": function() {
				let link_type = frappe.query_report.get_filter_value('link_type');
				if(link_type !== "Customer") {
					frappe.throw(__("Please First Select Linked To Customer"));
				}
				return "Territory";
			}
		},
		{
			"fieldname":"customer_group",
			"label": "Customer Group",
			"fieldtype": "Link",
			"reqd": 0,
			"get_options": function() {
				let link_type = frappe.query_report.get_filter_value('link_type');
				if(link_type !== "Customer") {
					frappe.throw(__("Please First Select Linked To Customer"));
				}
				return "Customer Group";
			}
		},
		{
			"fieldname":"orphaned",
			"label": "Orphaned",
			"fieldtype": "Check",
			"reqd": 0,
		},
	]
}
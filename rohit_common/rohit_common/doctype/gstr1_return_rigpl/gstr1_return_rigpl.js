// Copyright (c) 2021, Rohit Industries Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('GSTR1 Return RIGPL', {
	refresh: function(frm){
		cur_frm.cscript.lock_fields(frm)
	},
	onload: function(frm) {
		cur_frm.cscript.lock_fields(frm)
	    frm.set_query("address", function(doc){
	        return{
	            filters: {
	                "is_your_company_address": 1
	            }
	        }
	    });

	}
});

cur_frm.cscript.lock_fields = function(frm){
    var read_only_value = frm.doc.fully_validated;
    var locked_tables = ["b2b_invoices", "b2cl_invoices", "cdn_b2b", "cdn_b2c", "export_invoices",
    "b2c_invoices", "hsn_summary", "b2ba_invoices", "b2cla_invoices", "b2csa_invoices", "cdb_b2ba", "cdn_b2ca",
    "export_amend"]
    for (var i = 0; i < locked_tables.length; i++){
        frm.set_df_property(locked_tables[i], "read_only", read_only_value);
    }
};

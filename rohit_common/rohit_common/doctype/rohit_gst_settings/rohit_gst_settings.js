// Copyright (c) 2021, Rohit Industries Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('GST Registration Details', {
    request_otp: function(frm, dt, dn) {
        var child = locals[dt][dn];
        if (child.api_access_authorized !== 1) {
            frappe.call({
                method: "rohit_common.rohit_common.india_gst_api.gst_api.get_gst_otp",
                args: {
                    "gstin": child.gst_registration_number
                },
                callback: function(r){
                    if (!r.exc){
                        frm.reload_doc();
                    }
                }
            });
        } else {
            frappe.msgprint("For Row# " + child.idx + " and GSTIN# " + child.gst_registration_number + " API Access is Already there so No Need for OTP")
        }
    },
    validate_otp: function(frm, dt, dn){
        var child = locals[dt][dn];
        if (child.api_access_authorized !== 1 && child.otp){
            frappe.call({
                method: "rohit_common.rohit_common.india_gst_api.gst_api.authenticate_gst_otp",
                args: {
                    "gstin": child.gst_registration_number,
                    "otp": child.otp,
                    "row_id": child.name
                },
                callback: function(r){
                    if (!r.exc){
                        frm.reload_doc();
                    }
                }
            });
        } else {
            frappe.msgprint("For Row# " + child.idx + " Either API Access is Already there or NO OTP is Entered for Verification")
        }
    },
});

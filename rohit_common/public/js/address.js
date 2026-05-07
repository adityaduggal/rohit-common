frappe.ui.form.on("Address", {
    onload: function(frm) {
        frm.set_query("state_rigpl", function(doc) {
            return {
				"filters": {
					"country": frm.doc.country
				}
            };
        });
    },
	onload_post_render: function(frm) {
		if (frm.doc.latitude && frm.doc.longitude) {
            var marker = L.marker([frm.doc.latitude, frm.doc.longitude]).addTo(frm.fields_dict.location.map);
            marker.bindPopup(frm.doc.address_title).openPopup();
			frm.fields_dict.location.map.setView([frm.doc.latitude, frm.doc.longitude], 20);
		} else {
			frm.doc.latitude = frm.fields_dict.location.map.getCenter()['lat'];
			frm.doc.longitude = frm.fields_dict.location.map.getCenter()['lng'];
		}
    },
    // Changes on changing country field would the reset_flds to no valuue so that you need to enter them again
    // tin_no, excide_no are legacy fields neeeded for old excise invoices prior to GST invoices 01-Jul-2017
    country: function(frm) {
        var reset_flds = ["state", "state_rigpl", "gstin", "gst_state", "gst_state_number", "tin_no", 
        "excise_no", "latitude", "longitude", "global_google_code", "known_states"];

        for (let fld of reset_flds) {
            let df = frappe.meta.get_docfield("Address", fld, frm.doc.name);
            let value = (df && df.fieldtype === "Check") ? 0 : "";
            frm.set_value(fld, value);
        }
        frm.refresh_fields();

    },
    state_rigpl: function(frm) {
        frm.doc.gst_state = frm.doc.state_rigpl;
        frm.doc.gst_state_number = frm.doc.gstin.substring(0, 2);
        frm.refresh_fields();
    },
    gstin: function(frm) {
        var reset_flds = ["validated_gstin", "gstin_json_reply", "gst_status", "gst_validation_date"];
        frm.doc.gst_state = frm.doc.state_rigpl;
        frm.doc.gst_state_number = frm.doc.gstin.substring(0, 2);
        for (let fld of reset_flds) {
            frm.doc[fld] = "" ;
        }
        frm.refresh_fields();
    },
});
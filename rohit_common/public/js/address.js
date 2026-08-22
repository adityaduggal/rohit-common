frappe.ui.form.on("Address", {
    /**
     * Form load handler.
     * Restricts the "State RIGPL" link field's dropdown to states belonging
     * to the address's currently selected country.
     */
    onload: function (frm) {
        frm.set_query("state_rigpl", function (doc) {
            return {
                "filters": {
                    "country": frm.doc.country
                }
            };
        });
    },
    /**
     * Runs once the form (including the Leaflet map widget) has finished
     * rendering. If the address already has coordinates, drops a marker on
     * the map and centers/zooms to it; otherwise seeds the address's
     * latitude/longitude from the map's default center so a new address
     * starts with a sensible location.
     */
    onload_post_render: function (frm) {
        if (frm.doc.latitude && frm.doc.longitude) {
            var marker = L.marker([frm.doc.latitude, frm.doc.longitude]).addTo(frm.fields_dict.location.map);
            marker.bindPopup(frm.doc.address_title).openPopup();
            frm.fields_dict.location.map.setView([frm.doc.latitude, frm.doc.longitude], 20);
        } else {
            frm.doc.latitude = frm.fields_dict.location.map.getCenter()['lat'];
            frm.doc.longitude = frm.fields_dict.location.map.getCenter()['lng'];
        }
    },
    /**
     * Fires when the "Country" field changes.
     * Clears fields whose values are country-specific (state, GSTIN/GST
     * fields, TIN/excise numbers, coordinates, Google location code) since
     * they no longer apply once the country changes.
     *
     * Note: the "known_states" checkbox is not set here — it is declared on
     * the Address doctype with fetch_from "country.known_states", so the
     * framework fetches it from the Country doc automatically whenever this
     * field changes. "State RIGPL" itself is shown/hidden via its
     * depends_on ("eval: doc.known_states === 1") and its mandatory-ness for
     * such countries is enforced server-side in
     * validations/address.py::country_validation.
     */
    country: function (frm) {
        var reset_flds = ["state", "state_rigpl", "gstin", "gst_state", "gst_state_number", "tin_no",
            "excise_no", "latitude", "longitude", "global_google_code"];

        for (let fld of reset_flds) {
            frm.doc[fld] = "";
        }
        frm.refresh_fields();

    },
    /**
     * Fires when "State RIGPL" changes.
     * Mirrors the selected state onto the GST state field and derives the
     * GST state number from the first two digits of the GSTIN.
     */
    state_rigpl: function (frm) {
        frm.doc.gst_state = frm.doc.state_rigpl;
        frm.doc.gst_state_number = frm.doc.gstin.substring(0, 2);
        frm.refresh_fields();
    },
    /**
     * Fires when "GSTIN" changes.
     * Clears previously stored GSTIN validation results (since they are now
     * stale) and re-derives the GST state/state number from the current
     * State RIGPL and GSTIN values.
     */
    gstin: function (frm) {
        var reset_flds = ["validated_gstin", "gstin_json_reply", "gst_status", "gst_validation_date"];
        frm.doc.gst_state = frm.doc.state_rigpl;
        frm.doc.gst_state_number = frm.doc.gstin.substring(0, 2);
        for (let fld of reset_flds) {
            frm.doc[fld] = "";
        }
        frm.refresh_fields();
    },
});

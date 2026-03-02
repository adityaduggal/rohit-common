frappe.provide("erpnext");

function override_transaction_controller(doctype) {
    frappe.ui.form.on(doctype, {
        setup: function(frm) {
            if (!erpnext.TransactionController) return;

            erpnext.TransactionController.prototype.confirm_posting_date_change = async function() {
                if (!frappe.meta.has_field(this.frm.doc.doctype, "set_posting_time")) return;
                if (this.frm.doc.set_posting_time) return;
                if (frappe.datetime.get_today() == this.frm.doc.posting_date) return;

                // Fetch the setting without throwing a permission error
                let is_confirmation_reqd = await frappe.call({
                    method: "rohit_common.api.get_accounts_settings_value",
                    args: { fieldname: "confirm_before_resetting_posting_date" }
                }).then(r => r.message);

                if (!is_confirmation_reqd) return;

                return new Promise((resolve, reject) => {
                    frappe.confirm(
                        __("Posting Date will change to today's date as Edit Posting Date and Time is unchecked. Are you sure want to proceed?"),
                        () => {
                            this.frm.doc.posting_date = frappe.datetime.get_today();
                            this.frm.refresh_field("posting_date");
                            resolve();
                        },
                        () => reject()
                    );
                });
            };
        }
    });
}

const transaction_doctypes = [
    "Sales Invoice", "Purchase Invoice", "Sales Order", "Purchase Order",
    "Quotation", "Delivery Note", "Purchase Receipt", "POS Invoice"
];

transaction_doctypes.forEach(override_transaction_controller);

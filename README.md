# Rohit ERPNext Extensions (Common)

`rohit_common` is a custom Frappe application (app version `0.0.1`) developed by Rohit Industries Group Private Limited. It serves as a central extension, validation, and integration utility layer for ERPNext. It includes robust integrations for Indian GST compliance (E-Invoicing and E-Way Bills via NIC APIs), automated data verification and sanitization, customized document validations, and background housekeeping tasks.

---

## Directory Structure

```
rohit_common/
├── MANIFEST.in
├── README.md                          # App documentation
├── requirements.txt                   # App Python dependencies
├── setup.py                           # Python package installer metadata
└── rohit_common/                      # Main source package
    ├── before_migrate_patches.py      # Schema/data migration corrections
    ├── hooks.py                       # Frappe framework hook declarations
    ├── modules.txt
    ├── patches.txt                    # System patch execution list
    ├── core/                          # Core DocType overrides
    │   └── file.py                    # Extended File DocType validations & permissions
    ├── config/                        # Desktop and workspace configurations
    ├── erpnext_api/                   # Integration layer with parent/remote ERP
    │   └── erpnext_api_common.py      # Fetch resources over REST API
    ├── india_gst_api/                 # Government portal/NIC integration
    │   ├── common.py                  # POS, UOM translations & endpoint settings
    │   ├── einv.py                    # E-Invoicing, IRN generation/cancellation
    │   ├── eway_bill_api.py           # E-Way Bill lifecycle & distance lookups
    │   ├── gst_api.py                 # GST portal verification APIs
    │   └── gst_public_api.py          # Public syntax/status lookup tools
    ├── public/                        # Front-end static assets
    │   └── js/                        # Custom Desk form scripts
    │       ├── address.js             # Address page extensions
    │       ├── asset.js               # Asset page enhancements
    │       ├── contact.js             # Contact form enhancements
    │       └── stct.js                # Sales Taxes & Charges Template form
    ├── rohit_common/                  # Custom DocTypes and metadata
    │   ├── doctype/                   # Custom DocType definitions
    │   │   ├── dates_and_types_of_pulled_eway_bills/
    │   │   ├── eway_bill/             # NIC E-Way Bill lifecycle document
    │   │   ├── eway_bill_items/       # Child table for E-Way Bill items
    │   │   ├── eway_bill_vehicles/    # Child table for E-Way Bill transport logs
    │   │   ├── global_emails/         # Cached email verification whitelist
    │   │   ├── gst_registration_details/
    │   │   ├── gst_return_status/
    │   │   ├── gst_returns_status/
    │   │   ├── gstr1_hsn_summary/     # GSTR-1 HSN breakdown
    │   │   ├── gstr1_return_invoices/
    │   │   ├── gstr1_return_rigpl/
    │   │   ├── gstr2_return_invoices/
    │   │   ├── gstr2a_rigpl/
    │   │   ├── pull_eway_bills/       # Settings to fetch remote e-way bills
    │   │   ├── rohit_gst_settings/    # GST integration credentials
    │   │   ├── rohit_settings/        # General app behavior configurations
    │   │   ├── state/                 # State codes and descriptions
    │   │   ├── transporters/          # Transporter registration documents
    │   │   └── transporters_quote/    # Transport cost comparisons
    │   ├── scheduled_tasks/           # Automated background/cron execution jobs
    │   │   ├── auto_delete_version.py # Version history cleanup
    │   │   ├── auto_einvoice_tasks.py # Async invoice submit & IRN generation
    │   │   ├── auto_refresh_gstin_auth_code.py # GST token renewal
    │   │   ├── auto_update_from_erp.py# Sync shipping bills from remote ERP
    │   │   ├── auto_update_gstin_status.py # Re-validate active GSTINs
    │   │   ├── delete_unneeded_files.py    # Orphan/stale file purge tasks
    │   │   └── email_queue_delete.py  # Outbound mail queue purge
    │   └── validations/               # Document event logic (validate, autoname)
    │       ├── address.py             # Address details & GSTIN verification hooks
    │       ├── asset.py               # Auto-naming, depreciation scheduling hooks
    │       ├── asset_category.py      # Category rules & character validations
    │       ├── contact.py             # Phone & email parsing validations
    │       ├── customer.py            # Sanitized naming hooks
    │       ├── docshare.py            # Recursive file/folder permission cascading
    │       ├── google_maps.py         # Geo-location, distance matrix helpers
    │       ├── payment_terms_template.py # Credit limits & day weights validation
    │       ├── purchase_invoice.py    # Taxes integrity & local vs import check hooks
    │       ├── sales_invoice.py       # Submission queues & GST validation hooks
    │       ├── stc_template.py        # Sales Taxes & Charges validation rules
    │       ├── supplier.py            # Supplier naming sanitizations
    │       └── user.py                # Placeholder for User validations
    └── utils/                         # Global helper methods
        ├── accounts_utils.py          # HSN compilers & accounting code converters
        ├── address_utils.py           # Address formatting checks
        ├── asset_utils.py             # Asset utility functions
        ├── background_doc_processing.py # Background submit/cancel loops
        ├── email_utils.py             # Bouncify API client validation wrapper
        ├── phone_utils.py             # google-libphonenumber formatting & parsing
        └── rohit_common_utils.py      # General sanitization & database checks
```

---

## Core Modules & Functionality

### 1. Indian GST Compliance (`india_gst_api/`)

This module provides direct integration with the Indian GST portal and E-Way/E-Invoice sandbox/production APIs via ASP/GSP endpoints:
* **E-Invoicing ([einv.py](file:///home/aditya/v12/apps/rohit_common/rohit_common/india_gst_api/einv.py))**:
  * Automated Invoice Reference Number (IRN) generation for Sales Invoices and debit/credit notes.
  * Generates, converts, and attaches QR Code images directly to the corresponding invoice.
  * Handles cancellation of IRNs and manages retries for duplicate error codes (e.g., Error Code `2150` for duplicate IRN).
* **E-Way Bills ([eway_bill_api.py](file:///home/aditya/v12/apps/rohit_common/rohit_common/india_gst_api/eway_bill_api.py))**:
  * Lifecycle operations: Generation, vehicle updates (Part-B), and cancellation.
  * Automates distance calculation between shipping and billing addresses utilizing Google Maps distance matrix API (maximum threshold capped at 3999 km).
  * Automatically fetches detailed PDF printouts of generated E-Way bills from NIC and saves them as attachments.
* **GSTIN Portal Verification ([gst_api.py](file:///home/aditya/v12/apps/rohit_common/rohit_common/india_gst_api/gst_api.py))**:
  * Validates GSTIN syntax.
  * Fetches registration information (status, taxpayer type, trade name) from the portal.
  * Automated renewal of active API access tokens.

### 2. Custom Business Logic & Validations (`validations/`)

Events in [hooks.py](file:///home/aditya/v12/apps/rohit_common/rohit_common/hooks.py) route document lifecycles through these hooks to enforce data integrity:
* **Address ([address.py](file:///home/aditya/v12/apps/rohit_common/rohit_common/validations/address.py))**:
  * Ensures pin codes contain only valid alphanumeric strings.
  * Checks the GSTIN prefix matching the numeric code of the chosen State.
  * Triggers portal lookup for validation, updating GST validation timestamps and details.
* **Asset & Category ([asset.py](file:///home/aditya/v12/apps/rohit_common/rohit_common/validations/asset.py), [asset_category.py](file:///home/aditya/v12/apps/rohit_common/rohit_common/validations/asset_category.py))**:
  * Generates automated asset naming serials with a check digit (format: `YYYYMM-CategoryShort-SerialDigit`).
  * Restricts asset short names to exactly three uppercase alphanumeric characters (excluding confusing characters 'I' and 'O').
  * Prevents changes to asset category details once submitted assets are associated.
* **Sales / Purchase Invoices ([sales_invoice.py](file:///home/aditya/v12/apps/rohit_common/rohit_common/validations/sales_invoice.py), [purchase_invoice.py](file:///home/aditya/v12/apps/rohit_common/rohit_common/validations/purchase_invoice.py))**:
  * Validates local vs. central tax templates based on shipping state and supplier/company state.
  * Matches naming series conventions with those registered on the Taxes and Charges template.
  * Enforces matching tax calculations between transaction records and the master template.
  * Asynchronously queues document submission if the invoice contains 10 or more items to prevent Desk timeouts.
* **DocShare ([docshare.py](file:///home/aditya/v12/apps/rohit_common/rohit_common/validations/docshare.py))**:
  * Implements recursive sharing: sharing or unsharing a folder propagates the exact permission flags (read, write, share, everyone) to all nested subfolders and files.

### 3. Core Overrides (`core/`)

* **File permissions and uploads ([file.py](file:///home/aditya/v12/apps/rohit_common/rohit_common/core/file.py))**:
  * Overrides standard permission handlers (`custom_file_permissions`) to resolve access queries for files shared or not attached to specific documents.
  * Prevents users from deleting files checked as `important_document_for_archive`.
  * Moves file paths between `/public/` and `/private/` assets depending on whitelists defined in settings.
  * Enhances file name searches, factoring in custom criteria declared on standard forms.

### 4. Asynchronous Scheduled Tasks (`scheduled_tasks/`)

Automated jobs executed via the Frappe scheduler:
* **`auto_update_gstin_status`**: Periodically re-validates GSTIN registrations older than the threshold specified in settings.
* **`auto_einvoice_tasks`**: Periodically processes drafts marked for submission and generates pending IRN records.
* **`auto_refresh_gstin_auth_code`**: Renews authentication API tokens daily.
* **`delete_unneeded_files`**: Cleans up files lacking URLs, purges files flagged for deletion, and moves files to designated archive directories.
* **`auto_delete_version`**: Prunes historical `Version` logs older than the threshold to minimize DB table bloat.
* **`auto_update_from_erp`**: Syncs export details (e.g. shipping bills) from a remote master ERP instance using login credentials.

### 5. Utility Layer (`utils/`)

* **`email_utils.py`**: Interfacing with the **Bouncify** API to filter out spamtrap, disposable, or invalid email IDs, maintaining clean communications lists in the `Global Emails` table.
* **`phone_utils.py`**: Uses `phonenumbers` to validate syntax and parse contact inputs, formatting phone numbers to `E164` standard format and detecting the line type.
* **`rohit_common_utils.py`**: Common tools for sanitizing inputs (trimming, title casing), checking system manager permissions, and sanitizing Document IDs from special characters.

---

## Configuration & Key DocTypes

### `Rohit Settings` (Single DocType)
Acts as the central configuration panel for the application.
* **E-Invoicing Rules**: Toggles automated e-invoicing (`enable_einvoice`) and defines the start date (`einvoice_applicable_date`).
* **Auto-Deletion Policies**: Lists document attachments to clean up, stating the age threshold (minimum 30 days) and custom SQL conditions.
* **Background Documents**: Registers which DocTypes can be processed asynchronously in background queues (`bg_submit_cancel_docs`).
* **Public Attachments**: Whitelists DocTypes (`docs_with_pub_att`) and Roles (`roles_allow_pub_att`) permitted to host files publicly.
* **Version Control**: Defines lifetime policies (`max_days_to_keep_version`) to limit database storage consumed by changes logs.

### `eWay Bill`
Directly implements NIC E-Way Bill operations:
* Tracks document number references, distances, vehicle details, and GST responses.
* Generates `Part-A` details based on active transaction documents.
* Performs `Part-B` updates for transporters, vehicle number corrections, and reasons.
* Fetches printable PDF copies directly using whitelisted connection tokens.

---

## Hooks Reference ([hooks.py](file:///home/aditya/v12/apps/rohit_common/rohit_common/hooks.py))

* **Overridden Whitelisted Methods**:
  * Overrides `frappe.core.doctype.file.file.get_files_by_search_text` to support customizable field lookups.
* **Custom Permissions**:
  * Resolves file permissions using `rohit_common.core.file.custom_file_permissions`.
* **Standard DocType JavaScript Hooks**:
  * `Address`: Extends address fields with Google Maps lookups via JS `address.js`.
  * `Asset`: Extends naming rules and serial allocations in JS `asset.js`.
  * `Contact`: Extension scripts loaded via JS `contact.js`.
  * `Sales Taxes and Charges Template`: Integrates layout rules via JS `stct.js`.
* **Before Migrate Hook**:
  * Runs migration patches using `rohit_common.before_migrate_patches.execute`.

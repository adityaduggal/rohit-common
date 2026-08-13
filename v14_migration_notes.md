# Version 14 Migration & Upgrade Notes

This document contains a consolidated list of modules, domains, and features that have been decoupled or moved to separate standalone applications starting in **Frappe / ERPNext Version 14**.

---

## Decoupled Modules & External Repositories

### 1. Chat Module
* **Status**: Removed from Frappe core in Version 13 / Version 14.
* **Replacement App**: [frappe/chat](https://github.com/frappe/chat)
* **Action Required**: Install the `chat` app on your bench if you utilize chat features.

### 2. Payment Gateways
* **Status**: Moved to a separate app in Version 14.
* **Replacement App**: [frappe/payments](https://github.com/frappe/payments)
* **Action Required**: Install the `payments` app when upgrading to Version 14.

### 3. Agriculture Domain
* **Status**: Decoupled from ERPNext in Version 14.
* **Replacement App**: [frappe/agriculture](https://github.com/frappe/agriculture)
* **Action Required**: Install the `agriculture` app if managing agricultural domain features.

### 4. Hospitality Domain
* **Status**: Decoupled from ERPNext in Version 14.
* **Replacement App**: [frappe/hospitality](https://github.com/frappe/hospitality)
* **Action Required**: Install the `hospitality` app if managing hotel/hospitality features.

### 5. DATEV Reports (German Localisation)
* **Status**: Decoupled from ERPNext in Version 14.
* **Replacement App**: [alyf-de/erpnext_datev](https://github.com/alyf-de/erpnext_datev)
* **Action Required**: Install `erpnext_datev` for DATEV exports.

### 6. Education Domain
* **Status**: Decoupled from ERPNext in Version 14.
* **Replacement App**: [frappe/education](https://github.com/frappe/education)
* **Action Required**: Install the `education` app for student/course management.

### 7. India Regional Features & Localisation
* **Status**: Moved to a dedicated standalone app in Version 14.
* **Replacement App**: [resilient-tech/india-compliance](https://github.com/resilient-tech/india-compliance)
* **Action Required**: Install `india-compliance` for Indian GST, e-Way Bills, and e-Invoicing capabilities in v14+.

### 8. HR and Payroll Modules
* **Status**: Moved to a separate app in Version 14.
* **Replacement App**: [frappe/hrms](https://github.com/frappe/hrms)
* **Action Required**: Install `hrms` when upgrading to Version 14 to preserve HR, Employee, and Payroll functionality.

---

## Migration Troubleshooting History

* **Sales Invoice `po_no` Column Truncation**:
  * **Symptom**: `pymysql.err.DataError: (1406, "Data too long for column 'po_no' at row 13012")` during schema sync.
  * **Fix**: Added pre-migration patch in `rohit_common.before_migrate_patches` to truncate `po_no` strings in `tabSales Invoice` to 140 characters prior to schema alteration.

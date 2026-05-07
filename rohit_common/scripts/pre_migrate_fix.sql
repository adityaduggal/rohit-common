-- =========================================
-- PRE-MIGRATE FIX SCRIPT (ERPNext v16)
-- Safe to rerun
-- =========================================

SET SQL_SAFE_UPDATES = 0;

DROP PROCEDURE IF EXISTS add_col_if_missing;
DROP PROCEDURE IF EXISTS modify_col_if_exists;
DROP PROCEDURE IF EXISTS set_zero_if_exists;
DROP PROCEDURE IF EXISTS skip_patch_if_missing;
DROP PROCEDURE IF EXISTS set_workspace_type_if_needed;
DROP PROCEDURE IF EXISTS trim_po_no_if_needed;

DELIMITER //

CREATE PROCEDURE add_col_if_missing(
    IN tbl_name VARCHAR(128),
    IN col_name VARCHAR(128),
    IN col_def TEXT
)
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = tbl_name
          AND column_name = col_name
    ) THEN
        SET @sql = CONCAT(
            'ALTER TABLE `', tbl_name, '` ADD COLUMN `', col_name, '` ', col_def
        );
        PREPARE stmt FROM @sql;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
    END IF;
END//

CREATE PROCEDURE modify_col_if_exists(
    IN tbl_name VARCHAR(128),
    IN col_name VARCHAR(128),
    IN col_def TEXT
)
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = tbl_name
          AND column_name = col_name
    ) THEN
        SET @sql = CONCAT(
            'ALTER TABLE `', tbl_name, '` MODIFY `', col_name, '` ', col_def
        );
        PREPARE stmt FROM @sql;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
    END IF;
END//

CREATE PROCEDURE set_zero_if_exists(
    IN tbl_name VARCHAR(128),
    IN col_name VARCHAR(128)
)
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = tbl_name
          AND column_name = col_name
    ) THEN
        SET @sql = CONCAT(
            'UPDATE `', tbl_name, '` ',
            'SET `', col_name, '` = 0 ',
            'WHERE `', col_name, '` IS NULL ',
            'OR CAST(`', col_name, '` AS CHAR) IN (''No'', '''')'
        );
        PREPARE stmt FROM @sql;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
    END IF;
END//

CREATE PROCEDURE skip_patch_if_missing(
    IN patch_name TEXT
)
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM `tabPatch Log`
        WHERE patch = patch_name
    ) THEN
        INSERT INTO `tabPatch Log` (`name`, `patch`)
        VALUES (UUID(), patch_name);
    END IF;
END//

CREATE PROCEDURE set_workspace_type_if_needed()
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = 'tabWorkspace'
          AND column_name = 'type'
    ) THEN
        UPDATE `tabWorkspace`
        SET `type` = 'Workspace'
        WHERE `name` = 'Rohit Common'
          AND (`type` IS NULL OR `type` = '');
    END IF;
END//

CREATE PROCEDURE trim_po_no_if_needed()
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = 'tabSales Invoice'
          AND column_name = 'po_no'
    ) THEN
        IF NOT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = 'tabSales Invoice'
              AND column_name = 'po_no_backup'
        ) THEN
            SET @sql = 'ALTER TABLE `tabSales Invoice` ADD COLUMN `po_no_backup` LONGTEXT';
            PREPARE stmt FROM @sql;
            EXECUTE stmt;
            DEALLOCATE PREPARE stmt;
        END IF;

        UPDATE `tabSales Invoice`
        SET `po_no_backup` = `po_no`
        WHERE CHAR_LENGTH(`po_no`) > 188
          AND (`po_no_backup` IS NULL OR `po_no_backup` = '');

        UPDATE `tabSales Invoice`
        SET `po_no` = LEFT(`po_no`, 188)
        WHERE CHAR_LENGTH(`po_no`) > 188;
    END IF;
END//

DELIMITER ;

-- =========================================
-- 1. CORE SCHEMA FIXES
-- =========================================

CALL add_col_if_missing('tabDocField', 'is_virtual', 'INT(1) NOT NULL DEFAULT 0');

CALL modify_col_if_exists('tabPatch Log', 'patch', 'VARCHAR(255)');
CALL add_col_if_missing('tabPatch Log', 'migration_hash', 'VARCHAR(140)');
CALL add_col_if_missing('tabDocType', 'migration_hash', 'VARCHAR(255)');

-- =========================================
-- 2. BOOLEAN DATA NORMALIZATION
-- =========================================

CALL set_zero_if_exists('tabPurchase Invoice', 'disable_rounded_total');
CALL set_zero_if_exists('tabPurchase Invoice', 'is_subcontracted');

CALL set_zero_if_exists('tabGL Entry', 'is_cancelled');
CALL set_zero_if_exists('tabGL Entry', 'to_rename');

CALL set_zero_if_exists('tabPurchase Order', 'disable_rounded_total');
CALL set_zero_if_exists('tabPurchase Order', 'group_same_items');
CALL set_zero_if_exists('tabPurchase Order', 'background_processing');
CALL set_zero_if_exists('tabPurchase Order', 'ignore_pricing_rule');
CALL set_zero_if_exists('tabPurchase Order', 'is_subcontracting');
CALL set_zero_if_exists('tabPurchase Order', 'is_subcontracted');

CALL set_zero_if_exists('tabStock Ledger Entry', 'is_cancelled');
CALL set_zero_if_exists('tabStock Ledger Entry', 'to_rename');

CALL set_zero_if_exists('tabPurchase Receipt', 'disable_rounded_total');
CALL set_zero_if_exists('tabPurchase Receipt', 'ignore_pricing_rule');
CALL set_zero_if_exists('tabPurchase Receipt', 'group_same_items');
CALL set_zero_if_exists('tabPurchase Receipt', 'set_posting_time');
CALL set_zero_if_exists('tabPurchase Receipt', 'is_return');
CALL set_zero_if_exists('tabPurchase Receipt', 'is_subcontracted');

-- =========================================
-- 3. SALES INVOICE FIXES
-- =========================================

SET @has_sales_invoice := (
    SELECT COUNT(*)
    FROM information_schema.tables
    WHERE table_schema = DATABASE()
      AND table_name = 'tabSales Invoice'
);

-- Only run if Sales Invoice exists
SET @sql = IF(@has_sales_invoice > 0, 'ALTER TABLE `tabSales Invoice` ROW_FORMAT=DYNAMIC', 'SELECT 1');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

CALL modify_col_if_exists('tabSales Invoice', 'customer_name', 'TEXT');
CALL modify_col_if_exists('tabSales Invoice', 'contact_display', 'TEXT');
CALL modify_col_if_exists('tabSales Invoice', 'remarks', 'TEXT');
CALL modify_col_if_exists('tabSales Invoice', 'base_in_words', 'TEXT');
CALL modify_col_if_exists('tabSales Invoice', 'in_words', 'TEXT');

CALL modify_col_if_exists('tabSales Invoice', 'po_no', 'LONGTEXT');
CALL modify_col_if_exists('tabSales Invoice', 'contact_mobile', 'TEXT');
CALL modify_col_if_exists('tabSales Invoice', 'contact_email', 'TEXT');
CALL modify_col_if_exists('tabSales Invoice', 'against_income_account', 'TEXT');
CALL modify_col_if_exists('tabSales Invoice', 'title', 'TEXT');
CALL modify_col_if_exists('tabSales Invoice', 'status', 'TEXT');
CALL modify_col_if_exists('tabSales Invoice', 'apply_discount_on', 'TEXT');

CALL modify_col_if_exists('tabSales Invoice', 'campaign', 'TEXT');
CALL modify_col_if_exists('tabSales Invoice', 'source', 'TEXT');
CALL modify_col_if_exists('tabSales Invoice', 'select_print_heading', 'TEXT');
CALL modify_col_if_exists('tabSales Invoice', 'mode_of_payment', 'TEXT');
CALL modify_col_if_exists('tabSales Invoice', 'shipping_rule', 'TEXT');
CALL modify_col_if_exists('tabSales Invoice', 'reason_for_issuing_document', 'TEXT');
CALL modify_col_if_exists('tabSales Invoice', 'invoice_type', 'TEXT');
CALL modify_col_if_exists('tabSales Invoice', 'export_type', 'TEXT');
CALL modify_col_if_exists('tabSales Invoice', 'transporters', 'TEXT');
CALL modify_col_if_exists('tabSales Invoice', 'transporter_name', 'TEXT');
CALL modify_col_if_exists('tabSales Invoice', 'driver_name', 'TEXT');

CALL modify_col_if_exists('tabSales Invoice', 'charge', 'TEXT');
CALL modify_col_if_exists('tabSales Invoice', 'in_words_export', 'TEXT');
CALL modify_col_if_exists('tabSales Invoice', 'shipping_location', 'TEXT');
CALL modify_col_if_exists('tabSales Invoice', 'ship_to', 'TEXT');
CALL modify_col_if_exists('tabSales Invoice', 'cancel_reason', 'TEXT');
CALL modify_col_if_exists('tabSales Invoice', 'delivery_note_main', 'TEXT');
CALL modify_col_if_exists('tabSales Invoice', 'sales_order_main', 'TEXT');

CALL modify_col_if_exists('tabSales Invoice', 'set_warehouse', 'TEXT');
CALL modify_col_if_exists('tabSales Invoice', 'scan_barcode', 'TEXT');
CALL modify_col_if_exists('tabSales Invoice', 'inter_company_invoice_reference', 'TEXT');
CALL modify_col_if_exists('tabSales Invoice', 'loyalty_program', 'TEXT');
CALL modify_col_if_exists('tabSales Invoice', 'auto_repeat', 'TEXT');
CALL modify_col_if_exists('tabSales Invoice', 'subscription', 'TEXT');

CALL modify_col_if_exists('tabSales Invoice', 'shipping_tin_no', 'VARCHAR(50)');
CALL modify_col_if_exists('tabSales Invoice', 'tin_no', 'VARCHAR(50)');
CALL modify_col_if_exists('tabSales Invoice', 'excise_no', 'VARCHAR(50)');
CALL modify_col_if_exists('tabSales Invoice', 'shipping_excise_no', 'VARCHAR(50)');
CALL modify_col_if_exists('tabSales Invoice', 'port_code', 'VARCHAR(50)');
CALL modify_col_if_exists('tabSales Invoice', 'ecommerce_gstin', 'VARCHAR(50)');
CALL modify_col_if_exists('tabSales Invoice', 'shipping_bill_number', 'VARCHAR(50)');
CALL modify_col_if_exists('tabSales Invoice', 'transporter', 'VARCHAR(80)');
CALL modify_col_if_exists('tabSales Invoice', 'gst_transporter_id', 'VARCHAR(80)');
CALL modify_col_if_exists('tabSales Invoice', 'vehicle_no', 'VARCHAR(80)');

CALL trim_po_no_if_needed();

-- =========================================
-- 4. PATCH FIXES / SKIPS
-- =========================================

CALL add_col_if_missing('tabNewsletter', 'content_type', 'VARCHAR(50)');

CALL set_workspace_type_if_needed();

CALL add_col_if_missing('tabProcess Statement Of Accounts', 'cc_to', 'TEXT');

CALL add_col_if_missing('tabCompany', 'enable_perpetual_inventory_for_non_stock_items', 'INT(1) DEFAULT 0');
CALL add_col_if_missing('tabCompany', 'service_received_but_not_billed', 'VARCHAR(255)');

CALL skip_patch_if_missing('frappe.patches.v13_0.update_notification_channel_if_empty');
CALL skip_patch_if_missing('erpnext.patches.v14_0.update_reports_with_range');

-- =========================================
-- 5. CLEANUP
-- =========================================

DROP PROCEDURE IF EXISTS add_col_if_missing;
DROP PROCEDURE IF EXISTS modify_col_if_exists;
DROP PROCEDURE IF EXISTS set_zero_if_exists;
DROP PROCEDURE IF EXISTS skip_patch_if_missing;
DROP PROCEDURE IF EXISTS set_workspace_type_if_needed;
DROP PROCEDURE IF EXISTS trim_po_no_if_needed;
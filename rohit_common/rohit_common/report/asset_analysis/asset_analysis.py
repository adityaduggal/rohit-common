# Copyright (c) 2022, Rohit Industries Group Pvt Ltd. and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe.utils import flt
from erpnext.accounts.utils import get_balance_on
from ....utils.asset_utils import get_ast_cat_finance, get_total_assets_for_item_code

def execute(filters=None):
    if not filters:
        filters = {}
    
    conditions, cond_dep, params = get_conditions(filters)
    columns = get_columns(filters)
    
    if filters.get("compare_accounts") == 1:
        data = compare_asset_with_accounts(filters)
    else:
        assets = get_assets(conditions, filters, params)
        acc_dep_list = get_acc_dep(assets, cond_dep, params)
        
        # O(1) Lookup Optimization
        acc_dep_map = {d.parent: d for d in acc_dep_list}
        
        data = []
        for a in assets:
            purchase = flt(a.net_purchase_amount)
            row = [
                a.name, a.item_code, a.purchase_date, purchase, 
                a.total_number_of_depreciations, a.opening_accumulated_depreciation
            ]
            
            acc = acc_dep_map.get(a.name)
            if acc:
                total_dep = flt(round(acc.dep, 2))
                period_dep = flt(round(acc.monthly, 2))
                row += [(total_dep - period_dep), total_dep, period_dep]
            else:
                # Fully depreciated fallback
                total_dep = purchase - flt(a.salvage)
                period_dep = 0
                row += [(total_dep - period_dep), total_dep, period_dep]
            
            row += [
                (purchase - total_dep), a.salvage, a.status, a.disposal_date,
                a.fixed_asset_account, a.asset_category,
                a.warehouse, a.model, a.manufacturer, a.description, a.purchase_receipt,
                a.purchase_invoice
            ]
            data.append(row)
            
    return columns, data

def compare_asset_with_accounts(filters):
    to_date = filters.get("to_date") or frappe.utils.today()
    
    # Respect filters in reconciliation mode
    item_conditions = ""
    item_params = {"to_date": to_date}

    if filters.get("asset_category"):
        item_conditions += " AND it.asset_category = %(asset_category)s"
        item_params["asset_category"] = filters.get("asset_category")
    
    # 1. Bulk fetch Fixed Asset items with reconciliation filters
    item_list = frappe.db.sql(f"""
        SELECT 
            it.name, it.description, it.asset_category,
            IFNULL(it.end_of_life, '2099-12-31') as eol, 
            ascat.type_of_asset
        FROM `tabItem` it
        INNER JOIN `tabAsset Category` ascat ON it.asset_category = ascat.name
        WHERE it.is_fixed_asset = 1 {item_conditions}
        ORDER BY it.name
    """, item_params, as_dict=1)
    
    if not item_list:
        return []

    # 2. Bulk fetch Asset Category Accounts (O(1) mapping)
    # Respect fixed_asset_account filter if provided
    acc_filters = {}
    if filters.get("account"):
        acc_filters["fixed_asset_account"] = filters.get("account")
        
    category_accounts = frappe.get_all("Asset Category Account", 
        filters=acc_filters,
        fields=["parent", "fixed_asset_account"])
    cat_acc_map = {d.parent: d.fixed_asset_account for d in category_accounts}

    # 3. Bulk calculate Asset Totals per Item Code (O(N) aggregation)
    asset_totals = frappe.db.sql("""
        SELECT 
            item_code, 
            COUNT(name) as no_of_assets,
            SUM(net_purchase_amount) as total_value
        FROM `tabAsset`
        WHERE docstatus = 1 AND purchase_date <= %s
        AND (disposal_date IS NULL OR disposal_date > %s)
        GROUP BY item_code
    """, (to_date, to_date), as_dict=1)
    asset_map = {d.item_code: d for d in asset_totals}

    # 4. Assembly with Bulk Balance fetching
    data = []
    account_balances = {}
    
    for itm in item_list:
        acc = cat_acc_map.get(itm.asset_category)
        if not acc: continue
        
        if acc not in account_balances:
            account_balances[acc] = get_balance_on(account=acc, date=to_date)
            
        stats = asset_map.get(itm.name, frappe._dict({"no_of_assets": 0, "total_value": 0}))
        
        acc_bal = flt(account_balances[acc])
        asset_val = flt(stats.total_value)
        
        data.append([
            itm.name, itm.asset_category, itm.eol, acc, itm.type_of_asset,
            acc_bal, asset_val, stats.no_of_assets, (acc_bal - asset_val)
        ])
        
    return data


def get_columns(filters):
    if filters.get("compare_accounts") == 1:
        return [
                "Item Code:Link/Item:120", "Asset Category:Link/Asset Category:120",
                "End of Life:Date:80", "Asset Account:Link/Account:200", "Type of Asset::120",
                "GL A/C Balance:Currency:120", "Asset A/C Balance:Currency:120",
                "Total Working Assets:Int:120", "Difference: Currency:120"
        ]
    else:
        return [
                "Asset:Link/Asset:150", "Item:Link/Item:150",
                "Purchase Date:Date:80", "Gross Purchase Amt:Currency:100", "Total # Dep:Int:60",
                "Op Acc Dep:Currency:100", "Op Dep Period:Currency:100",
                "Total Depreciation:Currency:100", "Period Dep:Currency:100",
                "Net Block:Currency:100", "Salvage Value:Currency:100",
                "Status::100", "Disposal Date:Date:80", "Account:Link/Account:200",
                "AssetCategory:Link/Asset Category:150", "Warehouse::150", "Model::150",
                "Manufacturer::150", "Description::250", "GRN:Link/Purchase Receipt:80",
                "PI:Link/Purchase Invoice:80"
        ]

def get_assets(conditions, filters, params):
    # Ensure to_date has a value for disposal check
    params["to_date"] = params.get("to_date") or frappe.utils.today()
    
    query = f"""
        SELECT 
            ass.name, ass.item_code, ass.asset_category,
            IFNULL(ass.warehouse, 'NIL') as warehouse, 
            IFNULL(ass.model, 'NIL') as model,
            IFNULL(ass.manufacturer, 'NIL') as manufacturer, 
            IFNULL(ass.status, 'NO STATUS') as status,
            IFNULL(ass.description, 'NIL') as description, 
            ass.purchase_date,
            ass.net_purchase_amount, 
            ass.opening_accumulated_depreciation,
            IFNULL(ass_fb.expected_value_after_useful_life, 0) AS salvage,
            IFNULL(ass.disposal_date, '2199-12-31') as disposal_date,
            ass_fb.total_number_of_depreciations, 
            as_cat_acc.fixed_asset_account, 
            ass.purchase_receipt,
            ass.purchase_invoice
        FROM `tabAsset` ass
        INNER JOIN `tabAsset Category` as_cat ON ass.asset_category = as_cat.name
        INNER JOIN `tabAsset Finance Book` ass_fb ON ass_fb.parent = ass.name
        INNER JOIN `tabAsset Category Account` as_cat_acc ON as_cat_acc.parent = as_cat.name
        WHERE ass.docstatus != 2 
        AND ass_fb.parenttype = 'Asset'
        AND IFNULL(ass.disposal_date, '2099-12-31') >= %(to_date)s
        {conditions}
        ORDER BY ass.purchase_date DESC, ass.asset_category
    """
    assets = frappe.db.sql(query, params, as_dict=1)
    
    if not assets:
        frappe.throw("No Assets in the Selected Criterion")
    return assets

def get_acc_dep(assets, cond_dep, params):
    if not assets:
        return []
    
    # Bulk Fetch targeted by asset names
    asset_names = [d.name for d in assets]
    dep_params = params.copy()
    
    # Secure and highly compatible dictionary expansion for IN clause
    placeholders = []
    for i, name in enumerate(asset_names):
        key = f"asset_name_{i}"
        dep_params[key] = name
        placeholders.append(f"%({key})s")
    
    query = f"""
        SELECT 
            MAX(ds.accumulated_depreciation_amount) as dep,
            ds.parent, 
            SUM(ds.depreciation_amount) as monthly
        FROM `tabDepreciation Schedule` ds
        WHERE ds.docstatus != 2 
        {cond_dep}
        AND ds.parent IN ({', '.join(placeholders)})
        GROUP BY ds.parent
    """
    
    return frappe.db.sql(query, dep_params, as_dict=1)

def get_conditions(filters):
    conditions = ""
    cond_dep = ""
    to_date = filters.get("to_date") or frappe.utils.today()
    params = {"to_date": to_date}

    if filters.get("from_date"):
        if filters["from_date"] > to_date:
            frappe.throw("From Date cannot be greater than To Date")
        cond_dep += " AND ds.schedule_date >= %(from_date)s"
        params["from_date"] = filters.get("from_date")

    if filters.get("to_date"):
        conditions += " AND ass.purchase_date <= %(to_date)s"
        cond_dep += " AND ds.schedule_date <= %(to_date)s"

    if filters.get("asset_category"):
        conditions += " AND ass.asset_category = %(asset_category)s"
        params["asset_category"] = filters.get("asset_category")

    if filters.get("asset"):
        conditions += " AND ass.name = %(asset)s"
        params["asset"] = filters.get("asset")

    if filters.get("account"):
        conditions += " AND as_cat_acc.fixed_asset_account = %(account)s"
        params["account"] = filters.get("account")

    return conditions, cond_dep, params

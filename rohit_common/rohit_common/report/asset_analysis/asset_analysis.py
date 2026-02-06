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
    conditions, cond_dep = get_conditions(filters)
    columns = get_columns(filters)
    if filters.get("compare_accounts") == 1:
        data = compare_asset_with_accounts(filters)
    else:
        assets = get_assets(conditions, filters)
        acc_dep = get_acc_dep(assets, cond_dep)
        data = []
        for a in assets:
            open_acc_dep = a.opening_accumulated_depreciation
            purchase = a.net_purchase_amount
            row = [a.name, a.item_code, a.purchase_date, purchase, a.total_number_of_depreciations,
            open_acc_dep]
            check = 0
            for acc in acc_dep:
                if acc.parent == a.name:
                    total_dep = flt(round(acc.dep,2))
                    period_dep = flt(round(acc.monthly, 2))
                    row += [(total_dep - period_dep), total_dep, period_dep]
                    check = 1
            if check == 0:  # if fully depreciated asset
                total_dep = purchase - a.salvage
                period_dep = 0
                row += [(total_dep - period_dep), total_dep, period_dep]
            row += [(purchase - total_dep), a.salvage, a.status, a.disposal_date,
            a.fixed_asset_account, a.asset_category,
            a.warehouse, a.model, a.manufacturer, a.description, a.purchase_receipt,
            a.purchase_invoice]

            data.append(row)
    return columns, data

def compare_asset_with_accounts(filters):
    """
    Returns the list of GRN or PI where Fixed Assets are not created
    """
    data = []
    item_list = frappe.db.sql("""SELECT it.name, it.description, it.asset_category,
        IFNULL(it.end_of_life, '2099-12-31') as eol, ascat.type_of_asset,
        ascat.residual_value_percent
        FROM `tabItem` it, `tabAsset Category` ascat
        WHERE it.is_fixed_asset = 1 AND it.asset_category = ascat.name
        ORDER BY it.name""", as_dict=1)
    for itm in item_list:
        ast_fin = get_ast_cat_finance(itm.asset_category)[0]
        tot_ast_dict = get_total_assets_for_item_code(item_code=itm.name,
            on_date=filters.get("to_date"))
        itm["asset_account"] = ast_fin.fixed_asset_account
        itm["asset_acc_balance"] = get_balance_on(account=ast_fin.fixed_asset_account,
            date=filters.get("to_date"))
        itm["working_assets"] = tot_ast_dict.no_of_assets
        itm["tot_asset_value"] = tot_ast_dict.total_value
        row = [
            itm.name, itm.asset_category, itm.eol, itm.asset_account, itm.type_of_asset,
            itm.asset_acc_balance, itm.tot_asset_value, itm.working_assets,
            (itm.asset_acc_balance - itm.tot_asset_value)
               ]
        data.append(row)
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

def get_assets(conditions, filters):
    query = """SELECT ass.name, ass.item_code, ass.asset_category,
        IFNULL(ass.warehouse, "NIL") as warehouse, IFNULL(ass.model, "NIL") as model,
        IFNULL(ass.manufacturer, "NIL") as manufacturer, IFNULL(ass.status, "NO STATUS") as status,
        IFNULL(ass.description, "NIL") as description, ass.purchase_date,
        ass.net_purchase_amount, ass.opening_accumulated_depreciation,
        IFNULL(ass_fb.expected_value_after_useful_life, 0) AS salvage,
        IFNULL(ass.disposal_date, '2199-12-31') as disposal_date,
        ass_fb.total_number_of_depreciations, as_cat_acc.fixed_asset_account, ass.purchase_receipt,
        ass.purchase_invoice
        FROM `tabAsset` ass, `tabAsset Category` as_cat, `tabAsset Category Account` as_cat_acc,
            `tabAsset Finance Book` ass_fb
        WHERE ass.docstatus != 2 AND ass.asset_category = as_cat.name
            AND ass_fb.parent = ass.name AND ass_fb.parenttype = 'Asset'
            AND IFNULL(ass.disposal_date, '2099-12-31') >= '%s'
            AND as_cat_acc.parent = as_cat.name  %s
        ORDER BY ass.purchase_date DESC, ass.asset_category""" %(filters.get("to_date"),conditions)
    #frappe.msgprint(query)
    assets = frappe.db.sql(query, as_dict = 1)
    if assets:
        pass
    else:
        frappe.throw("No Assets in the Selected Criterion")
    #frappe.msgprint(str(assets))
    return assets

def get_acc_dep(asset, cond_dep):
    acc_dep = frappe.db.sql("""SELECT MAX(ds.accumulated_depreciation_amount) as dep,
        ds.parent, SUM(ds.depreciation_amount) as monthly
        FROM `tabDepreciation Schedule` ds
        WHERE ds.docstatus != 2 {condition} AND ds.parent IN (%s)
        GROUP BY ds.parent""".format(condition = cond_dep) %
            (', '.join(['%s']*len(asset))), tuple([d.name for d in asset]), as_dict=1)
    return acc_dep

def get_conditions(filters):
    conditions = ""
    cond_dep = ""

    if filters.get("from_date"):
        if filters["from_date"] > filters["to_date"]:
            frappe.throw("From Date cannot be greater than To Date")
        cond_dep += "AND ds.schedule_date >= '%s'"% filters["from_date"]

    if filters.get("to_date"):
        conditions += "AND ass.purchase_date <= '%s'" % filters["to_date"]
        cond_dep += "AND ds.schedule_date <= '%s'"% filters["to_date"]

    if filters.get("asset_category"):
        conditions += "AND ass.asset_category = '%s'" % filters["asset_category"]

    if filters.get("asset"):
        conditions += "AND ass.name = '%s'" % filters["asset"]

    if filters.get("account"):
        conditions += "AND as_cat_acc.fixed_asset_account = '%s'" % filters["account"]


    return conditions, cond_dep

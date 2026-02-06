# Copyright (c) 2022, Rohit Industries Ltd. and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe


def get_ast_cat_finance(asset_category_name):
    """
    Returns a dict of the asset category with the following details:
    1. Asset Category Account (from child table)
    2. Depreciation Method (from child table) and other details
    """
    ass_det = frappe._dict({})
    ass_det["name"] = asset_category_name
    query = f"""SELECT fb.finance_book, fb.depreciation_method,
        fb.total_number_of_depreciations, fb.frequency_of_depreciation, asac.company_name,
        asac.fixed_asset_account, asac.accumulated_depreciation_account,
        asac.depreciation_expense_account, asac.capital_work_in_progress_account
        FROM `tabAsset Finance Book` fb, `tabAsset Category Account` asac
        WHERE fb.parent = '{asset_category_name}' AND asac.parent = '{asset_category_name}'
        ORDER BY fb.idx"""
    finance = frappe.db.sql(query, as_dict=1)

    if not finance:
        frappe.throw(f"No Finance Book Details for \
            {frappe.get_desk_link('Asset Category', asset_category_name)}")
    return finance

def get_total_assets_for_item_code(item_code, on_date, active=1):
    """
    Returns dictionary for the number and total value of Assets for an Item Code
    active=1 would return only current active asset numbers
    active=0 would return only currently inactive asset numbers
    active=2 would return all the submitted assets whether scrapped or sold
    On date is the status needed on that date
    """
    ast_dict = frappe._dict({})
    total_asst_value = 0
    if active == 0:
        disp_date_cond = f" AND IFNULL(asst.disposal_date, '2099-12-31') <= '{on_date}'"
    elif active == 1:
        disp_date_cond = f" AND IFNULL(asst.disposal_date, '2099-12-31') > '{on_date}'"
    else:
        disp_date_cond = ""
    query = f"""SELECT asst.name, asst.purchase_date, asst.status,
    IFNULL(asst.disposal_date, '2099-12-31') as disposal_date, asst.net_purchase_amount
    FROM `tabAsset` asst
    WHERE asst.docstatus = 1 AND asst.purchase_date <= '{on_date}'
    AND asst.item_code = '{item_code}' {disp_date_cond}
    ORDER BY asst.name"""
    assets = frappe.db.sql(query, as_dict=1)
    if not assets:
        frappe.msgprint(f"No Assets found for {frappe.get_desk_link('Item', item_code)}")
    ast_dict["no_of_assets"] = len(assets)
    for ast in assets:
        total_asst_value += ast.net_purchase_amount
    ast_dict["total_value"] = total_asst_value
    return ast_dict

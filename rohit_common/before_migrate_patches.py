# -*- coding: utf-8 -*-


import frappe
import erpnext
def execute ():
    add_default_company_fy()

def add_default_company_fy():
    fyd = frappe.db.get_list('Fiscal Year', fields=['name'], order_by='year_start_date asc')
    def_comp = erpnext.get_default_company()
    for fy in fyd:
        fyc = frappe.db.get_list("Fiscal Year Company", filters={"parent": fy.name,
                                                                 "parentfield": "companies",
                                                                 "parenttype": "Fiscal Year"})
        if not fyc:
            print(f"No Company defined for FY {fy.name} so setting to Default Company {def_comp}")
            fydoc = frappe.get_doc("Fiscal Year", fy.name)
            fydoc.append("companies", {"company": def_comp})
            fydoc.save()
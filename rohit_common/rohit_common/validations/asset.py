# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import frappe
from frappe.utils import getdate, get_last_day, flt, cint, add_months, add_days, date_diff
from rohit_common.utils.rohit_common_utils import fn_next_string, fn_check_digit
from dateutil import relativedelta

def validate(doc, method):
    if doc.calculate_depreciation == 0:
        doc.calculate_depreciation = 1
    ass_cat = frappe.get_doc("Asset Category", doc.asset_category)
    dep_freq, tot_no_of_deps, dep_meth = get_defaults(ass_cat)
    if doc.is_existing_asset != 1:
        doc.opening_accumulated_depreciation = 0
        doc.number_of_depreciations_booked = 0
    else:
        if doc.opening_accumulated_depreciation == 0:
            doc.number_of_depreciations_booked = 0
    if doc.finance_books:
        if len(doc.finance_books) != 1:
            frappe.throw("Only 1 Line is Allowed in Finance Books Table")
        else:
            for d in doc.finance_books:
                if d.depreciation_method != 'Manual':
                    d.expected_value_after_useful_life = round((ass_cat.residual_value_percent *
                            doc.gross_purchase_amount)/100,0)
                    exp_val_aft_life = d.expected_value_after_useful_life
                    d.frequency_of_depreciation = dep_freq
                    d.depreciation_method = dep_meth
                    d.total_number_of_depreciations = tot_no_of_deps
                else:
                    tot_no_of_deps = d.total_number_of_depreciations
                    dep_freq = d.frequency_of_depreciation
                    exp_val_aft_life = d.expected_value_after_useful_life

    else:
        fb_list = []
        fb_dict = {}
        fb_dict.setdefault("depreciation_method", dep_meth)
        fb_dict.setdefault("depreciation_start_date", doc.purchase_date)
        fb_dict.setdefault("total_number_of_depreciations", tot_no_of_deps)
        fb_dict.setdefault("frequency_of_depreciation", dep_freq)
        exp_val_aft_life = round((ass_cat.residual_value_percent * doc.gross_purchase_amount)/100,0)
        fb_dict.setdefault("expected_value_after_useful_life", exp_val_aft_life)
        fb_list.append(fb_dict)
        for d in fb_list:
            doc.append("finance_books", d)
        #frappe.throw("Finance Book Entry is Mandatory")
    # base_dep_date = get_next_dep_date(doc, dep_freq, tot_no_of_deps)
    # make_dep_schedule(doc, base_dep_date, exp_val_aft_life, dep_freq, tot_no_of_deps)

def autoname(doc, method):
    if doc.get_automatic_name == 1:
        ass_cat = frappe.get_doc("Asset Category", doc.asset_category)
        purchase = getdate(doc.purchase_date)
        #name = YearMonth-AssetCategorySmall-SerialCheckDigit
        #Don't use - in the actual name for check digit
        name = str(purchase.year) + str('{:02d}'.format(purchase.month)) + \
                ass_cat.asset_short_name + str(ass_cat.serial)
        next_serial = fn_next_string(doc, str(ass_cat.serial))
        cd = fn_check_digit(name)
        name = name + str(cd)
        doc.name = name
        #frappe.db.set_value("Item Attribute Value", fa[0][0], "serial", next_serial)
        frappe.db.set_value("Asset Category", ass_cat.name, "serial", next_serial)
    else:
        doc.name = doc.asset_name
    doc.asset_name = doc.name

def get_next_dep_date(doc, dep_freq, tot_dep):
    #Next depreciation date shoud be last date of the purchase date if monthly or last date
    #of period of depreciation
    #if monthly depreciation then last day or month, if bi-monthly then last day of month+1
    #if 3 monthly then last day of quarter and not 3 months
    #if 4 monthly then last day of third and not 4 months and so on and so forth
    fy_doc = get_fy_doc(doc)
    r = relativedelta.relativedelta(add_days(fy_doc.year_end_date,1), fy_doc.year_start_date)
    fy_months = r.years*12 + r.months
    dep_in_fy = cint(fy_months)/flt(dep_freq)
    booked_deps_months = (cint(doc.number_of_depreciations_booked)*cint(dep_freq))
    last_day = add_months(get_last_day(doc.purchase_date), booked_deps_months)
    base_last_day = get_last_day(doc.purchase_date)
    base_dep_date = None
    if dep_in_fy >= 1 and dep_in_fy % 1 == 0:
        for i in range(0, cint(tot_dep)):
            dep_date = get_last_day(add_months(fy_doc.year_start_date, (i*dep_freq -1)))
            if base_last_day <= dep_date and base_dep_date is None:
                base_dep_date = dep_date

            if last_day <= dep_date:
                doc.next_depreciation_date = dep_date
                break
            else:
                doc.next_depreciation_date = fy_doc.year_end_date
    elif dep_in_fy % 1 != 0:
        frappe.throw('Frequency Causing Depreciations not to be posted equally in FY, \
            please change the frequency of depreciation')
    else:
        frappe.throw('Months between depreciation cannot be less than 1')
    return base_dep_date

def make_dep_schedule(doc, base_dep_date, exp_val_aft_life, dep_freq, tot_dep):
    dont_make_sch = 0
    fy_doc = get_fy_doc(doc)
    diff_pd_npd = relativedelta.relativedelta(add_days(base_dep_date,1), getdate(doc.purchase_date))
    diff_months = diff_pd_npd.years*12 + diff_pd_npd.months
    diff_days = date_diff(add_days(doc.next_depreciation_date,1), doc.purchase_date)
    fy_days = date_diff(fy_doc.year_end_date, fy_doc.year_start_date)
    middle_purchase_factor = flt(diff_days)/flt(fy_days)

    if tot_dep == cint(doc.number_of_depreciations_booked):
        doc.opening_accumulated_depreciation = (doc.gross_purchase_amount - exp_val_aft_life)
        doc.schedules = []
        dont_make_sch = 1
    else:
        if doc.opening_accumulated_depreciation == (doc.gross_purchase_amount - exp_val_aft_life):
            doc.number_of_depreciations_booked = tot_dep
            doc.schedules = []
            dont_make_sch = 1

    if doc.depreciation_method != 'Manual':
        doc.schedules = []

    if dont_make_sch != 1:
        if not doc.get("schedules") and doc.next_depreciation_date:
            value_after_depreciation = doc.gross_purchase_amount - doc.opening_accumulated_depreciation

            if diff_months < dep_freq:
                number_of_pending_depreciations = cint(tot_dep) - \
                        cint(doc.number_of_depreciations_booked) + 1
            else:
                number_of_pending_depreciations = cint(tot_dep) - \
                                cint(doc.number_of_depreciations_booked)

            if number_of_pending_depreciations:
                for n in range(number_of_pending_depreciations):
                    schedule_date = get_last_day(add_months(doc.next_depreciation_date,
                            n * cint(dep_freq)))

                    if diff_months < dep_freq and n==0 and \
                            cint(doc.number_of_depreciations_booked) == 0:
                        depreciation_amount = get_depreciation_amount(doc,
                                value_after_depreciation, middle_purchase_factor)
                    else:
                        depreciation_amount = get_depreciation_amount(doc,
                                value_after_depreciation, 1)
                    value_after_depreciation = value_after_depreciation - flt(depreciation_amount)

                    doc.append("schedules", {
                            "schedule_date": schedule_date,
                            "depreciation_amount": depreciation_amount
                    })
            #frappe.throw(str(number_of_pending_depreciations))
        accumulated_depreciation = flt(doc.opening_accumulated_depreciation)
        value_after_depreciation = flt(doc.value_after_depreciation)
        for i, d in enumerate(doc.get("schedules")):
            depreciation_amount = flt(d.depreciation_amount, d.precision("depreciation_amount"))

            if i==len(doc.get("schedules"))-1 and doc.depreciation_method == "Straight Line":
                depreciation_amount = flt((doc.gross_purchase_amount) - flt(accumulated_depreciation) - flt(exp_val_aft_life),
                        d.precision("depreciation_amount"))

            d.depreciation_amount = depreciation_amount
            accumulated_depreciation += d.depreciation_amount
            d.accumulated_depreciation_amount = flt(accumulated_depreciation,
                    d.precision("accumulated_depreciation_amount"))


def get_depreciation_amount(doc, depreciable_value, middle_purchase_factor):
    dep_freq, tot_no_of_deps, dep_meth, exp_val_aft_life = get_defaults(doc)

    if dep_meth in ("Straight Line", "Manual"):
        depreciation_amount = round((flt(doc.gross_purchase_amount) -
                flt(exp_val_aft_life) - flt(doc.opening_accumulated_depreciation))*
                middle_purchase_factor / (cint(tot_no_of_deps) -
                cint(doc.number_of_depreciations_booked)),0)
    else:
        factor = 200.0 / tot_no_of_deps
        depreciation_amount = flt(depreciable_value * factor / 100, 0)

        value_after_depreciation = flt(depreciable_value) - depreciation_amount
        if value_after_depreciation < flt(exp_val_aft_life):
            depreciation_amount = flt(depreciable_value) - flt(exp_val_aft_life)
    return depreciation_amount

def get_fy_doc(doc):
    fy = frappe.db.sql("""SELECT name FROM `tabFiscal Year`
        WHERE year_start_date <= '%s' AND year_end_date >= '%s'"""
            %(doc.purchase_date, doc.purchase_date), as_list=1)
    if fy:
        fy_doc = frappe.get_doc("Fiscal Year", fy[0][0])
    else:
        frappe.throw("No Fiscal Year Defined for {}".format(doc.purchase_date))
    return fy_doc

def get_defaults(document):
    dep_freq = 0
    tot_no_of_deps = 0
    dep_meth = ""
    exp_val_aft_life = 0
    for d in document.finance_books:
        dep_freq = d.frequency_of_depreciation
        tot_no_of_deps = d.total_number_of_depreciations
        dep_meth = d.depreciation_method
        exp_val_aft_life = d.expected_value_after_useful_life
    if document.doctype == 'Asset':
        return dep_freq, tot_no_of_deps, dep_meth, exp_val_aft_life
    else:
        return dep_freq, tot_no_of_deps, dep_meth

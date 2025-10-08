# Copyright (c) 2022 Rohit Industries Group Private Limited and Contributors.
# For license information, please see license.txt
# -*- coding: utf-8 -*-

from __future__ import unicode_literals
import frappe
import re
import ast
from datetime import date
from frappe.utils import flt, getdate
from difflib import SequenceMatcher as sm
from .google_maps import update_doc_json_from_geocode, render_gmap_json_text
from ..india_gst_api.gst_public_api import search_gstin
from ...utils.email_utils import comma_email_validations
from ...utils.address_utils import all_address_text_validations
from ...utils.phone_utils import comma_phone_validations
from ...utils.rohit_common_utils import get_country_code,replace_java_chars, check_system_manager,\
    check_or_rename_doc
from india_compliance.gst_india.api_classes.public import PublicAPI
from india_compliance.gst_india.utils.test_gstin_info import TestGstinInfo

def autoname(doc, method):
    backend = 0
    if doc.flags.ignore_mandatory == 1:
        backend = 1
    check_or_rename_doc(doc, backend)


def validate(doc, method):
    """
    Contains various validations for an Address Doctype
    """
    validate_dynamic_links(doc)
    all_address_text_validations(doc)
    backend = 1
    if not doc.flags.ignore_mandatory:
        backend = 0
        country_validation(doc)
        gstin_validation(doc)
        check_need_for_geocode(doc)
    ccode = get_country_code(country=doc.country, all_caps=1, backend=backend)
    doc.phone = comma_phone_validations(doc.phone, ccode, backend)
    doc.fax = comma_phone_validations(doc.fax, ccode, backend)
    doc.email_id = comma_email_validations(doc.email_id, backend=backend)
    validate_primary_address(doc)
    validate_shipping_address(doc)
    check_or_rename_doc(doc, backend)


def gstin_validation(doc):
    """
    Validates the GST first for the syntax of GST and then if the syntax is OK it would
    validate the GST from GSTIN portal
    """
    if doc.gstin:
        if doc.gstin != "NA":
            if len(doc.gstin) != 15:
                frappe.msgprint("GSTIN should be exactly as 15 digits or NA", raise_exception=1)
            else:
                valid_chars_gstin = "0123456789ABCDEFGIHJKLMNOPQRSTUVYWXZ"
                for n, char in enumerate(reversed(doc.gstin)):
                    if not valid_chars_gstin.count(char):
                        frappe.msgprint("Only Numbers and alphabets in UPPERCASE are allowed in GSTIN or NA",
                                        raise_exception=1)
                if doc.state_rigpl:
                    state = frappe.get_doc("State", doc.state_rigpl)
                else:
                    frappe.throw("Selected State is NOT Valid for {0}".format(doc.state_rigpl))
                if doc.gstin[:2] != state.state_code_numeric:
                    # fetch and update the state automatically else throw error
                    state_from_gst = frappe.db.sql("""SELECT name FROM `tabState`
                    WHERE state_code_numeric = '%s'""" % (doc.gstin[:2]), as_list=1)
                    if state_from_gst:
                        doc.state_rigpl = state_from_gst[0][0]
                        doc.gst_state = state_from_gst[0][0]
                        doc.state = state_from_gst[0][0]
                    else:
                        frappe.throw("State Selected {0} for Address {1}, GSTIN number should begin with {2}".
                                     format(doc.state_rigpl, doc.name, state.state_code_numeric))
                validate_gstin_from_portal(doc)
            doc.pan = doc.gstin[2:12]
        else:
            doc.pan = ""
            doc.validated_gstin = ""
            doc.gstin_json_reply = ""
            doc.gst_status = ""
    else:
        if doc.country == 'India':
            frappe.throw('GSTIN Mandatory for Indian Addresses or Enter NA for NO GSTIN')


def country_validation(doc):
    """
    Runs through various validations of a country specified as per the country doc
    """
    doc.pincode = re.sub('[^A-Za-z0-9]+', '', str(doc.pincode))
    if doc.country:
        country_doc = frappe.get_doc("Country", doc.country)
        if country_doc.gst_details != 1:
            doc.gstin = 'NA'
            doc.gst_state = ""
            doc.gst_state_number = ""

        if country_doc.known_states == 1:
            # Country has known states means state doctype should have states for that country
            state_list = frappe.db.sql(f"""SELECT name FROM `tabState`
                WHERE country = '{doc.country}'""", as_dict=1)
            if state_list:
                if doc.state_rigpl is None or not doc.state_rigpl or doc.state_rigpl == "":
                    if doc.state:
                        doc.state_rigpl = doc.state
                    else:
                        frappe.throw(f"State RIGPL for Country {doc.country} is Mandatory in Address {doc.name}")
                    # frappe.throw(f"State RIGPL for Country {doc.country} is Mandatory in \
                    #     Address {doc.name}")
                if country_doc.pincode_length:
                    pincode_length = replace_java_chars(country_doc.pincode_length)
                    if 'or' in pincode_length:
                        pc_length = pincode_length.split("or")
                    else:
                        pc_length = [pincode_length]
                    pincode_pass = 0
                    for d in pc_length:
                        if len(doc.pincode) == flt(d):
                            pincode_pass = 1
                    if pincode_pass != 1:
                        frappe.throw(f"For Address {doc.name}: Pincode should be {pincode_length} \
                            Digits Long")
                if country_doc.pincode_regular_expression:
                    pincode_regex = replace_java_chars(country_doc.pincode_regular_expression)
                    if 'or' in pincode_regex:
                        pc_regex = pincode_regex.split("or")
                    else:
                        pc_regex = [pincode_regex]
                    pc_regex_pass = 0
                    for alp in pc_regex:
                        comp_alp = re.compile(alp.strip())
                        if not comp_alp.match(doc.pincode):
                            pass
                        else:
                            pc_regex_pass = 1
                    if pc_regex_pass != 1:
                        frappe.throw(f"Country {doc.country}: Pin Code Should be of Format \
                            {pincode_regex}")
            else:
                frappe.throw("For Country {} no states exists in State Table".format(doc.country))
        else:
            doc.state_rigpl = ""
            if doc.pincode is None:
                frappe.throw("If Pin Code is not Known then Enter NA")
        if doc.state_rigpl:
            doc.state = doc.state_rigpl
            verify_state_country(doc.state_rigpl, doc.country)
    else:
        frappe.throw('Country is Mandatory')


def verify_state_country(state, country):
    """
    Verifies if the state mentioned belongs to a country or not
    """
    state_doc = frappe.get_doc("State", state)
    if state_doc.country != country:
        frappe.throw(f"State {state} belongs to Country {state_doc.country} hence choose correct \
            State or Change Country to {state_doc.country}")


def validate_dynamic_links(doc):
    """
    Only System Admins can make the Address for Company and Is Your Company Address Check Box
    should be checked
    """
    if doc.is_your_company_address == 1:
        # Check if the Dynamic Link has Link Doctype as Company & only Sys Admin can
        # edit such addresses
        user = frappe.get_user()
        is_sys_mgr = check_system_manager(user.name)
        if is_sys_mgr != 1:
            frappe.throw(f"Only System Admins are Allowed to Create Company Addresses")
    else:
        if doc.links:
            for d in doc.links:
                if d.link_doctype == "Company":
                    frappe.throw(f"{frappe.get_desk_link(doc.doctype, doc.name)} is Not Company \
                        Address hence cannot have Dynamic Link for Company")
        else:
            frappe.throw(f"{frappe.get_desk_link(doc.doctype, doc.name)} Cannot be Orphaned and \
                hence needs Dynamic Link Table to be Populated")


def validate_primary_address(doc):
    """
    Validate that there can only be one primary address for particular customer, supplier
    """
    if doc.is_primary_address == 1:
        unset_other(doc, "is_primary_address")
    else:
        # This would check if there is any Primary Address if not then would make current as
        # Primary address
        check = check_set(doc, "is_primary_address")
        if check == 0:
            doc.is_primary_address = 1


def validate_shipping_address(doc):
    """
    Validate that there can only be one shipping address for particular customer, supplier
    """
    if doc.is_shipping_address == 1:
        unset_other(doc, "is_shipping_address")
    else:
        # This would check if there is any Shipping Address if not then would make current as Shipping address
        check = check_set(doc, "is_shipping_address")
        if check == 0:
            doc.is_shipping_address = 1


def unset_other(doc, is_address_type):
    """
    If current address is Primary then other is unset
    """
    for link in doc.links:
        other_add = frappe.db.sql(f"""SELECT parent FROM `tabDynamic Link`
        WHERE link_doctype = '{link.link_doctype}' AND link_name = '{link.link_name}'
        AND parent != '{doc.name}' AND parenttype = '{doc.doctype}'""", as_list=1)
    for add in other_add:
        frappe.db.set_value(doc.doctype, add[0], is_address_type, 0)


def check_set(doc, is_address_type):
    """
    Returns Boolean for checking whether Primary is Set or not
    """
    for lnk in doc.links:
        other_add = frappe.db.sql(f"""SELECT parent FROM `tabDynamic Link`
        WHERE link_doctype = '{lnk.link_doctype}' AND link_name = '{lnk.link_name}'
        AND parent != '{doc.name}' AND parenttype = '{doc.doctype}'""", as_list=1)
        chk = 0
        for add in other_add:
            chk = chk + flt(frappe.db.get_value(doc.doctype, add[0], is_address_type))
    return chk


def check_id(doc):
    """
    Disallow Special Characters in Customer ID
    """
    new_name = re.sub('[^A-Za-z0-9\\-]+', ' ', doc.name)
    entered_name = doc.name
    return new_name, entered_name


def check_need_for_geocode(doc):
    """
    Gets Google Geocoding as per the checkboxes direction
    """
    if doc.dont_update_from_google == 1:
        remove_google_updates(doc)
    else:
        if not doc.json_reply:
            update_doc_json_from_geocode(doc)
            address_dict = render_gmap_json_text(doc.json_reply)
            if address_dict:
                update_fields_from_gmaps(doc, address_dict)
        else:
            json_dict = ast.literal_eval(doc.json_reply)
            if json_dict.get("status") == "OK":
                address_dict = render_gmap_json_text(doc.json_reply)
                if address_dict:
                    update_fields_from_gmaps(doc, address_dict)
            else:
                update_doc_json_from_geocode(doc)


def remove_google_updates(doc):
    """
    Removes google updates from Address document
    """
    doc.json_reply = ""
    doc.latitude = ""
    doc.longitude = ""
    doc.global_google_code = ""
    doc.approximate_location = 0


def update_fields_from_gmaps(doc, address_dict):
    """
    Updates the common fields from Geocoded Address
    """
    if doc.country == address_dict["country"]:
        if address_dict.get("global_code"):
            doc.global_google_code = address_dict.get("global_code")
        if doc.latitude != address_dict.get("lat"):
            doc.latitude = address_dict.get("lat")
        if doc.longitude != address_dict.get("lng"):
            doc.longitude = address_dict.get("lng")
        if address_dict.get("partial_match") != 1:
            if doc.update_from_google == 1:
                frappe.msgprint("Updating Address Automatically from Google Maps")
                if doc.country != address_dict.get("country"):
                    doc.country = address_dict.get("country")
                if doc.state != address_dict.get("state"):
                    doc.state = address_dict.get("state")
                if doc.city != address_dict.get("city"):
                    # frappe.msgprint(str(address_dict))
                    if address_dict.get("city") == "":
                        doc.city = "NA"
                    else:
                        doc.city = address_dict.get("city")
                if doc.address_line1 != address_dict.get("address_line1"):
                    doc.address_line1 = address_dict.get("address_line1")
                add_line2 = address_dict.get("sublocal1", "") + ", " + address_dict.get("sublocal2", "") \
                            + ", " + address_dict.get("locality", "")
                if doc.address_line2 != add_line2:
                    doc.address_line2 = add_line2
                if doc.pincode != address_dict.get("postal_code"):
                    doc.pincode = address_dict.get("postal_code")
            else:
                frappe.msgprint("You can update Address: {} directly from Google. For this Click on Check "
                                "Box to Update Directly from Google.".format(doc.name))
        else:
            doc.approximate_location = 1
    else:
        doc.dont_update_from_google = 1
        remove_google_updates(doc)


def validate_gstin_from_portal(doc):
    """
    Validates GSTIN using India Compliance Public API
    """
    auto_days = flt(frappe.get_value("Rohit Settings", "Rohit Settings",
        "auto_validate_gstin_after"))
    if doc.gst_validation_date:
        days_since_validation = (date.today() - getdate(doc.gst_validation_date)).days
    else:
        days_since_validation = 999

    if doc.validated_gstin != doc.gstin or days_since_validation >= auto_days:
        try:
            if frappe.get_single("GST Settings").sandbox_mode:
                class DummyAPI:
                    def is_ignored_error(self, _):
                        return False

                api = DummyAPI()
                gstin_json = TestGstinInfo.MOCK_GSTIN_INFO
            else:
                api = PublicAPI()
                api.setup(doc=doc)
                gstin_json = api.get_gstin_info(doc.gstin)
        except Exception as e:
            frappe.throw(f"Error validating GSTIN {doc.gstin}: {e}")

        # ignored/invalid responses
        if api.is_ignored_error(gstin_json):
            doc.gstin_json_reply = str(gstin_json)
            doc.validated_gstin = doc.gstin
            doc.gst_status = gstin_json.get("sts") or "Invalid"
            doc.gst_validation_date = date.today()
        else:
            # normal success response
            doc.gstin_json_reply = str(gstin_json)
            doc.validated_gstin = gstin_json.get("gstin")
            doc.gst_status = gstin_json.get("sts")
            doc.gst_validation_date = date.today()

    # disabling logic
    if doc.gst_status in ('Inactive', 'Cancelled'):
        doc.disabled = 1
    elif doc.gst_status == 'Suspended':
        dl_list = frappe.db.sql(f"""SELECT name, link_doctype FROM `tabDynamic Link`
            WHERE parenttype = 'Address' AND parent = %s""", (doc.name,), as_dict=1)
        if dl_list:
            for dt in dl_list:
                if dt.link_doctype == 'Supplier':
                    doc.disabled = 1
        else:
            doc.disabled = 1

    update_address_title_from_gstin_json(doc)


def update_address_title_from_gstin_json(doc):
    """
    Checks the legal name or Trade Name and if its within 60% match then copies that in Addres Title
    """
    if doc.validated_gstin:
        if doc.validated_gstin == doc.gstin:
            gst_json = ast.literal_eval(doc.gstin_json_reply)
            if gst_json.get("status_cd", 1) == 1:
                # Now Check the Legal Name lgnm and Also another field is Trade Name (tradeNam)
                lgl_name = gst_json.get("lgnm")
                trd_name = gst_json.get("tradeNam")
                lgl_ratio = sm(lambda x: x in (" ", ".", ",", "(", ")"), (doc.address_title).lower(),
                               lgl_name.lower()).ratio()
                trd_ratio = sm(lambda x: x in (" ", ".", ",", "(", ")"), (doc.address_title).lower(),
                               trd_name.lower()).ratio()
                if lgl_ratio > 0.6:
                    # Update Address Title from Legal Name
                    doc.address_title = lgl_name
                    frappe.msgprint(f"Updated Address Title from Legal Name on GST Website for \
                        {doc.name}")
                elif trd_ratio > 0.6:
                    # Update Address Title from Legal Name
                    doc.address_title = trd_name
                    frappe.msgprint(f"Updated Address Title from Trade Name on GST Website for \
                        {doc.name}")

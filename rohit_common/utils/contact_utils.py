# Copyright (c) 2022, Rohit Industries Ltd. and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
from six import iteritems
import frappe
from frappe.desk.reportview import get_match_cond
from .email_utils import single_email_validations
from .phone_utils import single_phone_validations
from .address_utils import get_country_for_master
from .rohit_common_utils import separate_csv_in_table, get_country_code, santize_listed_txt_fields


@frappe.whitelist()
def rigpl_contact_query(doctype, txt, searchfield, start, page_len, filters):
    link_doctype = filters.pop("link_doctype")
    link_name = filters.pop("link_name")

    condition = ""
    meta = frappe.get_meta("Contact")
    for fieldname, value in iteritems(filters):
        if meta.get_field(fieldname) or fieldname in frappe.db.DEFAULT_COLUMNS:
            condition += " and {field}={value}".format(
                field=fieldname, value=frappe.db.escape(value))

    searchfields = meta.get_search_fields()

    if searchfield and (meta.get_field(searchfield) or searchfield in frappe.db.DEFAULT_COLUMNS):
        searchfields.append(searchfield)

    columns = ""
    if searchfields:
        for fld in searchfields:
            columns += f", `tabContact`.{fld}"

    search_condition = ""
    for field in searchfields:
        if search_condition == "":
            search_condition += "`tabContact`.`{field}` like %(txt)s".format(
                field=field)
        else:
            search_condition += " or `tabContact`.`{field}` like %(txt)s".format(
                field=field)

    return frappe.db.sql(
        """select
            `tabContact`.name, `tabContact`.first_name, `tabContact`.last_name {columns}
        from
            `tabContact`, `tabDynamic Link`
        where
            `tabDynamic Link`.parent = `tabContact`.name and
            `tabDynamic Link`.parenttype = 'Contact' and
            `tabDynamic Link`.link_doctype = %(link_doctype)s and
            `tabDynamic Link`.link_name = %(link_name)s and
            ({search_condition})
            {mcond} {condition}
        order by
            if(locate(%(_txt)s, `tabContact`.name), locate(%(_txt)s, `tabContact`.name), 99999),
            `tabContact`.idx desc, `tabContact`.name
        limit %(start)s, %(page_len)s """.format(
            columns=columns,
            mcond=get_match_cond(doctype),
            key=searchfield,
            search_condition=search_condition,
            condition=condition or "",
        ),
        {
            "txt": "%" + txt + "%",
            "_txt": txt.replace("%", ""),
            "start": start,
            "page_len": page_len,
            "link_name": link_name,
            "link_doctype": link_doctype,
        },
    )


def all_contact_text_validations(con_doc, backend=False):
    """
    Sanitizes all the text fields as pe the field dict
    """
    field_dict = [frappe._dict({})]

    field_dict = [
        {"field_name": "first_name", "case": "title"}, {
            "field_name": "middle_name", "case": "title"},
        {"field_name": "last_name", "case": "title"}, {
            "field_name": "designation", "case": "title"},
        {"field_name": "notes", "case": ""}, {
            "field_name": "department", "case": "title"}
    ]
    santize_listed_txt_fields(con_doc, field_dict)


def all_contact_phone_validations(con_doc, backend=True):
    """
    Runs various contact phone related validations serially.
    """
    validate_contact_phones(con_doc, backend)
    exactly_one_primary_phone(con_doc)


def all_contact_email_validations(con_doc, backend=True):
    """
    Runs various contact email related validations serially.
    """
    validate_contact_emails(con_doc, backend)
    exactly_one_primary_email(con_doc)


def exactly_one_primary_phone(con_doc):
    """
    Makes exactly 1 mobile as Primary and 1 Phone as Primary for a Contact.
    Should be run on validated phone numbers only. Also populates the mobile
    and phone number fields for a contact
    """
    pm_ph, pm_mb = get_no_of_primary_phones(con_doc)
    csv_ph, csv_mob = "", ""
    for row in con_doc.phone_nos:
        if row.is_mobile == 1:
            if pm_mb == 0:
                row.is_primary_mobile_no = 1
                pm_mb += 1
            if csv_mob == "":
                csv_mob += row.phone
            else:
                csv_mob += f", {row.phone}"
        else:
            if pm_ph == 0:
                row.is_primary_phone = 1
                pm_ph += 1
            if csv_ph == "":
                csv_ph += row.phone
            else:
                csv_ph += f", {row.phone}"
    con_doc.mobile_no = csv_mob
    con_doc.phone = csv_ph


def get_no_of_primary_phones(con_doc):
    """
    Returns the number of primary_mobile and primary_phones for a contact
    """
    pm_ph, pm_mb = 0, 0
    for row in con_doc.phone_nos:
        if row.is_primary_mobile_no == 1:
            pm_mb += 1
        if row.is_primary_phone == 1:
            pm_ph += 1
    return pm_ph, pm_mb


def update_phone_row_with_validation(ph_row, valid_ph_dict, rmv_ph_list):
    """
    Returns Phone row after analysing the validated phone dict supplied and also
    returns the Remove phone list
    """
    if valid_ph_dict:
        if valid_ph_dict.phone_validation == 0:
            rmv_ph_list.append(ph_row.phone)
        else:
            ph_row.phone = valid_ph_dict.phone
            if valid_ph_dict.phone_validation == 1:
                ph_row.is_valid = 1
                ph_row.is_possible = 0
            else:
                frappe.msgprint(f"Phone No:{ph_row.phone} entered seems possible but there could \
                    be some error in Entering the Phone. Kindly check again")
                ph_row.is_valid = 0
                ph_row.is_possible = 1
            if valid_ph_dict.phone_type == 1:
                ph_row.is_primary_phone = 0
                ph_row.is_mobile = 1
            else:
                ph_row.is_primary_mobile_no = 0
                ph_row.is_mobile = 0
    else:
        rmv_ph_list.append(ph_row.phone)

    return rmv_ph_list


def validate_or_populate_phone_country(con_doc, backend=True):
    """
    If Country is filled then checks if the guess country is Single then it needs to Match
    Else it can be different. If there is no country then it would fill the guessed country if
    there is a guess available
    """
    for row in con_doc.phone_nos:
        guessed_country = get_contact_country(con_doc)
        if not row.country:
            if guessed_country:
                row.country = guessed_country
        else:
            if guessed_country:
                if row.country != guessed_country:
                    message = f"For {frappe.get_desk_link(con_doc.doctype, con_doc.name)} in \
                    Contact Numbers Table Row# {row.idx} Country Entered = {row.country} whereas \
                    Guessed Country = {guessed_country}.<br>Kindly check the discrepancey \
                    and change the same"
                    if backend == 1:
                        print(message)
                    else:
                        frappe.throw(message)


def get_contact_country_code(con_doc):
    """
    Returns a Contact's country codes based on Masters or Address Linked
    1. If address is linked to a contact then it returns that address's country
    2. If No Address then it would check the masters of linked and check the addresses of those
    masters and if there is only 1 country then return that country else return NONE
    """
    country = get_contact_country(con_doc)
    if country:
        ctr_code = frappe.get_value("Country", country, "code").upper()
    else:
        ctr_code = ""
    return ctr_code


def get_contact_country(con_doc):
    """
    Returns a country for a contact by Guessing the linked to Master
    1. If linke to customer or supplier, it would check the customer address countries.
    2. If linked to Employee check address doc else return Company Linked Country
    3. If Linked to Warehouse check address doc else return company linked country
    4. Otherwise return NONE
    """
    if con_doc.address:
        country = frappe.get_value("Address", con_doc.address, "country")
    elif con_doc.links:
        country = ""
        for lnk in con_doc.links:
            def_country = get_country_for_master(
                lnk.link_doctype, lnk.link_name)
            if country == "" and def_country:
                country = def_country
    else:
        country = ""
    return country


def validate_contact_master(con_doc, backend=True):
    """
    It would validate if a contact is linked to a Master like Supplier, Customer etc
    If not then it would raise exception in case its not backend whereas in Backend it would just
    print a message.
    It would also check if the contact has email or phone number missing phone and
    email is not allowed
    """
    if not con_doc.email_ids and not con_doc.phone_nos:
        message = f"{frappe.get_desk_link(con_doc.doctype, con_doc.name)} does not have either \
        Mobile or Email Address mentioned one of the Two is Mandatory"
        if backend == 1:
            print(message)
        else:
            frappe.throw(message)
    # Frappe makes a Contact with no links for each new User (user.create_contact)
    if not con_doc.links and not con_doc.user:
        message = f"{frappe.get_desk_link(con_doc.doctype, con_doc.name)} is not Linked to Any \
        Master"
        if backend == 1:
            print(message)
        else:
            frappe.throw(message)


def validate_contact_phones(con_doc, backend=True):
    """
    Validates the phones in a Contact document's Phone Table
    If row in table has multiple phone numbers then it would separate the row in to multiple rows
    Also it would remove the invalid phones and also would populate the phone number field
    """
    remove_phones = []
    if con_doc.phone_nos:
        separate_csv_in_table(
            document=con_doc, tbl_name="phone_nos", field_name="phone")
        validate_or_populate_phone_country(con_doc, backend=backend)
        for row in con_doc.phone_nos:
            ctr_code = get_country_code(
                country=row.country, all_caps=1, backend=backend)
            if ctr_code:
                val_ph_dict = single_phone_validations(
                    row.phone, ctr_code, backend)
                remove_phones = update_phone_row_with_validation(ph_row=row,
                                                                 valid_ph_dict=val_ph_dict, rmv_ph_list=remove_phones)
            else:
                if backend == 1:
                    print("pass")
                else:
                    frappe.throw(f"For Country:{row.country} Country Code may be Empty.")
    if remove_phones:
        for rmv_ph in remove_phones:
            frappe.msgprint(f"Phone No: {rmv_ph} is Invalid and is Being Removed")
            [con_doc.phone_nos.remove(phn) for phn in con_doc.get('phone_nos')
             if phn.phone == rmv_ph]


def validate_contact_emails(con_doc, backend=True):
    """
    Validates the emails in a Contact document's Email Table
    If row in table has multiple email IDs then it would separate the row in to multiple rows
    Also it would remove the invalid emails and also would populate the email address field
    """
    remove_emails = []
    if con_doc.email_ids:
        separate_csv_in_table(
            document=con_doc, tbl_name="email_ids", field_name="email_id")
    for row in con_doc.email_ids:
        valid_email = single_email_validations(row.email_id, backend=backend)
        if valid_email:
            row.email_id = valid_email
        else:
            remove_emails.append(row.email_id)
    if remove_emails:
        for rmv_eml in remove_emails:
            message = f"Email ID: {rmv_eml} is being removed since its not valid"
            if backend == 1:
                print(message)
            else:
                frappe.msgprint(message)
            [con_doc.email_ids.remove(eml) for eml in con_doc.get(
                'email_ids') if eml.email_id == rmv_eml]


def exactly_one_primary_email(con_doc):
    """
    Makes exactly one email ID as primary and would populate the email ID field
    """
    ct_pri_em = 0
    for row in con_doc.email_ids:
        if row.is_primary == 1:
            if ct_pri_em == 0:
                ct_pri_em += 1
                con_doc.email_id = row.email_id
            else:
                row.is_primary = 0
    if ct_pri_em == 0:
        for row in con_doc.email_ids:
            row.is_primary = 1
            con_doc.email_id = row.email_id
            break


def get_contact_phones(con_name):
    """
    Returns phone numbers as CSV text for a Contact Name
    """
    phones = ""
    if "'" in con_name:
        cond = f'''"{con_name}"'''
    else:
        cond = f"""'{con_name}'"""
    query = f"""SELECT phone FROM `tabContact Phone`
        WHERE parenttype = 'Contact' AND parent = {cond}"""
    ph_nos = frappe.db.sql(query, as_dict=1)
    if ph_nos:
        for phone_nos in ph_nos:
            if phones == "":
                phones += phone_nos.phone
            else:
                phones += ", " + phone_nos.phone
    return phones


def get_contact_emails(con_name):
    """
    Returns emails for a Contact Name
    """
    emails = ""
    if "'" in con_name:
        cond = f'''"{con_name}"'''
    else:
        cond = f"""'{con_name}'"""
    em_dict = frappe.db.sql(f"""SELECT email_id FROM `tabContact Email`
        WHERE parenttype = 'Contact' AND parent = {cond}""", as_dict=1)
    if em_dict:
        for email in em_dict:
            if emails == "":
                emails += email.email_id
            else:
                emails += ", " + email.email_id
    return emails

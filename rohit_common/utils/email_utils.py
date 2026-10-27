#  Copyright (c) 2022. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt

import json
import frappe
import requests
from datetime import datetime
from frappe.utils import flt, validate_email_address

timeout = 15


def comma_email_validations(csv_email, backend=True):
    """
    Returns comma separated validated emails
    """
    validated_csv = ""
    if csv_email:
        em_list = csv_email.split(",")
        for email in em_list:
            val_email = single_email_validations(email, backend)
            if val_email:
                if validated_csv:
                    validated_csv += f", {val_email}"
                else:
                    validated_csv = val_email
    return validated_csv



def single_email_validations(email_id, backend=True):
    """
    Does various email validations and returns the validated email
    If the email is not validated then it returns blank
    - First it validates email as per frappe utils where the syntax is checked
    - Next it checks if the email is in Global emails and if not then it would check via bouncify
    """
    syntax_email = validate_email_address(email_id)
    if syntax_email:
        val_email = validate_global_email(syntax_email, backend=backend)
    else:
        val_email = ""
        message = f"{email_id} entered is Not A Valid Email ID"
        if backend == 1:
            print(message)
        else:
            frappe.msgprint(message)
    return val_email


def validate_global_email(email_id, backend=True):
    """
    Checks if Email in Global Emails DB and if not then bouncify email and
    if the email is deliverable then returns the email ID else prints message and returns null
    """
    glob_em = frappe.db.exists("Global Emails", email_id)
    message = ""
    if not glob_em:
        # Email ID Not in Global Email so need to check from Bouncify
        passed_email, success, response = process_bouncify_response(email_id, backend)
        if success == 1:
            if response.result == "deliverable":
                if response.dispoable != 1 and response.spamtrap != 1:
                    create_gloabal_email(passed_email, response)
                else:
                    message = f"Email: {email_id} is a Disposable or Spam Trap Email"
                    passed_email = ""
            elif response.result == "accept all":
                frappe.msgprint(f"{passed_email} belongs to a Domain where Email ID cannot be \
                    verified for errors in Spellings")
                create_gloabal_email(passed_email, response)
            elif response.result == "unknown":
                frappe.msgprint(f"{passed_email} belongs to a Domain where Email ID cannot be \
                    verified by sending an Email")
                # frappe.msgprint(f"Passed Email = {passed_email} and Response = {response}")
                create_gloabal_email(passed_email, response)
            else:
                message = f"Email: {email_id} is Not Deliverable"
                passed_email = ""
        else:
            message = f"Email: {email_id} could not be verified from Bouncify"
            passed_email = email_id
    else:
        # One thing todo If the last update date of Global Email is stale we should re-verify email
        passed_email = email_id
    if message != "":
        if backend:
            print(message)
        else:
            frappe.msgprint(message)
    return passed_email


def create_gloabal_email(passed_email, response):
    """
    Creates a Global Email for passed email and response from Bouncify
    """
    new_glob = frappe.new_doc("Global Emails")
    new_glob.flags.ignore_permissions= True
    new_glob.email_id = passed_email
    new_glob.domain = response.domain
    new_glob.is_free = response.free_email
    new_glob.is_role = response.role
    new_glob.username = response.user
    new_glob.verified_on = datetime.now()
    if response.success == 1:
        if response.result == "deliverable":
            new_glob.verified = 1
    if response.accept_all == 1:
        new_glob.is_accept_all = response.accept_all
    new_glob.insert()


def process_bouncify_response(email_id, backend=True):
    """
    Processes response from Bouncify so if there is error in processing the response
    then email_id is returned as it is
    It returns 3 things, email_id, response and success boolean
    """
    credits_left = get_bouncify_credits()
    cred_mess = ""
    min_credits = frappe.get_value("Rohit Settings", "Rohit Settings", "minimum_credits")
    if flt(credits_left) < flt(min_credits):
        cred_mess = f"Credits Left in Your Bouncify Account = {credits_left}. Kindly Recharge"
    success = 0
    response = frappe._dict(json.loads(bouncify_email(email_id)))
    if response.success:
        # Got response from Bouncify
        success = 1
    else:
        # Some error in Bouncify response would return the email ID as it is
        message = f"{email_id} could not be Validated from Bouncify due to some Error and the \
        Error is {response}"
        if backend:
            if cred_mess != "":
                print(cred_mess)
            print(message)
        else:
            if cred_mess != "":
                frappe.msgprint(cred_mess)
            frappe.msgprint(message)
    return email_id, success, response


def bouncify_email(email_id):
    """
    Validates a email_id from bouncify and then would return response from bouncify
    """
    def_resp = '{"success": 0}'
    action = "verify"
    api_key, base_url = get_bouncify_api_key()
    headers = {"Accept": "application/json"}
    if api_key and base_url:
        full_url = f"{base_url}{action}?apikey={api_key}&email={email_id}"
        try:
            resp = requests.get(full_url, headers=headers, timeout=timeout)
        except requests.RequestException as e:
            # The URL has the API key, so log only the error type
            frappe.log_error(f"Bouncify verify failed for {email_id}: {type(e).__name__}",
                             "Bouncify Request Failed")
            return def_resp
        return resp.text
    else:
        return def_resp


def get_bouncify_credits():
    """
    Returns the credits balance for Bouncify. It is fetched once per request or job,
    not once per email (#20).
    """
    if getattr(frappe.local, "bouncify_credits", None) is None:
        frappe.local.bouncify_credits = fetch_bouncify_credits()
    return frappe.local.bouncify_credits


def fetch_bouncify_credits():
    action = "info"
    api_key, base_url = get_bouncify_api_key()
    if api_key and base_url:
        full_url = f"{base_url}{action}?apikey={api_key}"
        try:
            resp = requests.get(full_url, timeout=timeout)
        except requests.RequestException as e:
            frappe.log_error(f"Bouncify credits check failed: {type(e).__name__}", "Bouncify Request Failed")
            return 0
        return resp.text
    else:
        return 0


def get_bouncify_api_key():
    """
    Gets Bouncify login details
    """
    rset = frappe.get_single("Rohit Settings")
    base_url, api_key = "", ""
    if rset.email_base_link:
        base_url = rset.email_base_link
        api_key = rset.email_api_key
    return api_key, base_url

# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import re
import ast
import json
import frappe
import requests
import urllib.parse

file_format = "json"
timeout = 15

def get_distance_matrix(origin, dest, mode='driving', units='metric'):
    key = get_google_maps_api_key()
    url = get_google_maps_url() + 'distancematrix/json?'
    # find_data =
    full_url = url + 'units=' + units +'&origins=' + origin + '&destinations=' + dest + '&mode=' + mode + "&key=" + key
    characters = [" ", "#"]
    for chrc in characters:
        full_url = full_url.replace(chrc, "+")
    try:
        response = requests.get(url=full_url, timeout=timeout)
    except requests.RequestException as e:
        # The URL has the API key, so log only the error type
        frappe.throw(f"Google Maps did not reply ({type(e).__name__}). Enter the distance by hand.")
    response_json = json.loads(response.content)
    # print(response_json)
    return response_json


def get_approx_dist_frm_matrix(dist_matrix, unit="km"):
    if dist_matrix.get('status') != 'OK':
        frappe.throw(f"Google Maps could not find the distance: {dist_matrix.get('status')}. "
                     "Enter the distance by hand.")
    rows = dist_matrix.get('rows')[0]
    elements = rows.get('elements')[0]
    dist = elements.get('distance')
    dist_mts = dist.get('value')
    if unit=='km':
        dst = dist_mts/1000
    else:
        dst = dist_mts
    return dst


def get_geocoded_address_dict(adr_doc):
    """
    Returns a geocoded dictionary for an Address Doc
    """
    action = "geocode"
    adr_string_params = generate_address_string(adr_doc)
    json_reply = get_gmaps_json(action, adr_string_params)
    adr_dict = render_gmap_json(json_reply)

    return adr_dict


def get_geocoded_address_json(adr_doc):
    """
    Returns a geocoded JSON Reply for an Address Doc
    """
    action = "geocode"
    adr_string_params = generate_address_string(adr_doc)
    json_reply = get_gmaps_json(action, adr_string_params)
    return json_reply



def render_gmap_json(json_dict):
    """
    Returns a readable dictionary from Google Json Reply
    """
    add_dict = frappe._dict({})
    if json_dict.get("status") == "OK":
        address_comps = json_dict.get("results")[0].get("address_components")
        geometry = json_dict.get("results")[0].get("geometry")
        formatted_add = json_dict.get("results")[0].get("formatted_address")
        frappe.msgprint(str(formatted_add), "Check Address Format As Below")
        plus_codes = json_dict.get("results")[0].get("plus_code")
        type_of_poi = json_dict.get("results")[0].get("types")
        partial_match = json_dict.get("results")[0].get("partial_match")
        add_dict["partial_match"] = partial_match
        if plus_codes:
            add_dict["global_code"] = plus_codes.get("global_code")
        if type_of_poi[0] != 'subpremise' and len(type_of_poi)>1:
            add_dict["poi_type"] = type_of_poi[0]
        add_dict["lat"] = geometry.get("location").get("lat")
        add_dict["lng"] = geometry.get("location").get("lng")
        postal_code, country_long, country_short, state_long, city_long, locality, sublocal1, \
            sublocal2 = "", "", "", "", "", "", "", ""
        for comp in address_comps:
            if comp.get("types"):
                if comp.get("types")[0] == 'postal_code':
                    postal_code = comp.get("long_name")
            else:
                postal_code = ""
            if comp.get("types"):
                if comp.get("types")[0] == 'country':
                    country_long = comp.get("long_name")
                    country_short = comp.get("short_name")
            else:
                country_short = ""
            if comp.get("types"):
                if comp.get("types")[0] == 'administrative_area_level_1':
                    state_long = comp.get("long_name")
            else:
                state_long = ""
            if comp.get("types"):
                if comp.get("types")[0] == 'administrative_area_level_2':
                    city_long = comp.get("long_name")
            else:
                city_long = ""
            if comp.get("types"):
                if comp.get("types")[0] == 'locality':
                    locality = comp.get("long_name")
            else:
                locality = ""
            if comp.get("types"):
                if comp.get("types")[0] == 'political':
                    if comp.get("types")[1] == 'sublocality':
                        if comp.get("types")[2] == 'sublocality_level_1':
                            sublocal1 = comp.get("long_name")
                        elif comp.get("types")[2] == 'sublocality_level_2':
                            sublocal2 = comp.get("long_name")
            else:
                sublocal1 = ""
                sublocal2 = ""
        add_dict["postal_code"] = postal_code
        add_dict["country"] = country_long
        add_dict["state"] = state_long
        add_dict["city"] = city_long
        add_dict["locality"] = locality
        add_dict["sublocal1"] = sublocal1
        add_dict["sublocal2"] = sublocal2

        formatted_add = formatted_add.replace(sublocal2, "")
        formatted_add = formatted_add.replace(sublocal1, "")
        formatted_add = formatted_add.replace(locality, "")
        formatted_add = formatted_add.replace(city_long, "")
        formatted_add = formatted_add.replace(state_long, "")
        formatted_add = formatted_add.replace(postal_code, "")
        formatted_add = formatted_add.replace(country_long, "")
        formatted_add = formatted_add.replace(country_short, "")

        formatted_add = formatted_add.replace(",", " ")
        formatted_add = re.sub(' +', ' ', formatted_add)
        add_dict["address_line1"] = formatted_add
    else:
        # ZERO_RESULTS, OVER_DAILY_LIMIT, OVER_QUERY_LIMIT, REQUEST_DENIED,INVALID_REQUEST, UNKNOWN_ERROR
        frappe.msgprint("Unable to fetch the GMAPS data see the json reply")
    return add_dict


def generate_address_string(adr_doc):
    """
    Generates the address string for a Address doc based on fields defined
    """
    adr_fields = ["address_line1", "address_line2", "city", "county", "pincode", "state",
    "country"]
    adr_string = "address="
    for fld in adr_fields:
        if adr_doc.get(fld) and adr_doc.get(fld).strip() and adr_doc.get(fld).strip() !="None":
            adr_string += f"+{adr_doc.get(fld).strip()}"
    return adr_string


def update_doc_json_from_geocode(add_doc):
    """
    Updates address document Google JSON from Geocoding Reply
    """
    action = "geocode"
    adr_params = generate_address_string(add_doc)
    json_reply = get_gmaps_json(action, adr_params)
    add_doc.json_reply = str(json_reply)


def render_gmap_json_text(json_txt):
    """
    Returns a readable dictionary from Text of JSON reply saved in ERP
    """
    json_dict = ast.literal_eval(json_txt)
    add_dict = render_gmap_json(json_dict)

    return add_dict


def get_gmaps_json(action, parameters):
    """
    Returns the json reply for GMAP action and file Format
    """
    api_key, base_url = get_google_maps_key_url()
    full_url = f"{base_url}{action}/{file_format}?{parameters}&key={api_key}"
    replace_chars = [" ", "#"]
    for char in replace_chars:
        full_url = full_url.replace(char, "+")

    try:
        response = requests.get(url=full_url, timeout=timeout)
    except requests.RequestException as e:
        # The URL has the API key, so log only the error type. A non-OK status is
        # handled by the callers, and the next save tries again (#20).
        frappe.log_error(f"Google Maps {action} failed: {type(e).__name__}", "Google Maps Request Failed")
        return {"status": "REQUEST_FAILED"}
    response_json = json.loads(response.content)

    return response_json


def get_google_maps_key_url():
    """
    Returns google api_key and base_url
    """
    key = get_google_maps_api_key()
    base_url = get_google_maps_url()
    return key, base_url


def get_google_maps_api_key():
    """
    Returns google maps api key
    """
    gmapset = frappe.get_single("Google Settings")
    return gmapset.api_key


def get_google_maps_url():
    """
    Static returns the Google Maps API base URL
    """
    return "https://maps.googleapis.com/maps/api/"

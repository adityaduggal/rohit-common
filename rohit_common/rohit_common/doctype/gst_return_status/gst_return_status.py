# -*- coding: utf-8 -*-
# Copyright (c) 2020, Rohit Industries Ltd. and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from datetime import datetime
from frappe.model.document import Document
from erpnext.accounts.utils import get_fiscal_year
from india_compliance.gst_india.api_classes.public import PublicAPI


class GSTReturnStatus(Document):
    @frappe.whitelist()
    def get_return_status(self):
        today = datetime.today()
        self.returns = []
    
        if self.fiscal_year:
            tup = get_fiscal_year(fiscal_year=self.fiscal_year)
            if tup[1] < datetime.strptime('01-04-2017', '%d-%m-%Y').date():
                frappe.throw('Selected FY {} is before the GST Era'.format(tup[0]))
            elif tup[1] > today.date():
                frappe.throw('Selected FY {} has not Even Started'.format(tup[0]))

        api = PublicAPI()
        fy = format_gst_fy(self.fiscal_year)
        response = api.get_returns_info(self.gstin, fy)

        efiled_list = response.get("EFiledlist") or response.get("data")
        if efiled_list:
            self.json_reply = str(efiled_list)
            for d in efiled_list:
                temp_dict = frappe._dict({})
                temp_dict['valid_gst_return'] = 'Yes' if d.get('valid') == 'Y' else 'No'
                temp_dict['mode_of_filing'] = d.get('mof')
                temp_dict['date_of_filing'] = (
                    datetime.strptime(d.get('dof'), '%d-%m-%Y')
                ).date() if d.get('dof') else None
                temp_dict['return_period'] = d.get('ret_prd')
                temp_dict['return_type'] = d.get('rtntype')
                temp_dict['arn_number'] = d.get('arn')
                temp_dict['status'] = d.get('status')
                self.append("returns", temp_dict.copy())

def format_gst_fy(fy: str) -> str:
    """Convert ERPNext fiscal year like '20xx-20xx' to GST format '20xx-xx'."""
    if "-" in fy and len(fy) == 9:  # 'YYYY-YYYY'
        start, end = fy.split("-")
        return f"{start}-{end[-2:]}"
    return fy
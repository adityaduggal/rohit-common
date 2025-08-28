# -*- coding: utf-8 -*-
# Copyright (c) 2020, Rohit Industries Ltd. and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
import json
from datetime import datetime
from frappe.utils.data import getdate
from ...india_gst_api.gst_public_api import track_return
from frappe.model.document import Document
from erpnext.accounts.utils import get_fiscal_year


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
		response = track_return(self.gstin, self.fiscal_year)
		efiled_list = response.get('EFiledlist')
		# frappe.throw(str(efiled_list))
		if efiled_list:
			self.json_reply = str(efiled_list)
			for d in efiled_list:
				temp_dict = frappe._dict({})
				if d.get('valid') == 'Y':
					temp_dict['valid_gst_return'] = 'Yes'
				else:
					temp_dict['valid_gst_return'] = 'No'
				temp_dict['mode_of_filing'] = d.get('mof')
				temp_dict['date_of_filing'] = (datetime.strptime(d.get('dof'), '%d-%m-%Y')).date()
				temp_dict['return_period'] = d.get('ret_prd')
				temp_dict['return_type'] = d.get('rtntype')
				temp_dict['arn_number'] = d.get('arn')
				temp_dict['status'] = d.get('status')
				self.append("returns", temp_dict.copy())

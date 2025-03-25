# -*- coding: utf-8 -*-
# Copyright (c) 2020, Rohit Industries Ltd. and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
import os

from frappe.utils import flt, today
from frappe.model.document import Document


class RohitSettings(Document):
    def validate(self):
        if self.enable_einvoice == 1:
            if not self.einvoice_applicable_date:
                frappe.throw("E-Invoice Applicable Date is Mandatory")
            if self.eway_bill_limit < 1:
                frappe.throw(f"Enabling e-Invoice should enable Auto e-Way Bills for Invoices \
                    and Limit for the e-Way Bill should be greater than 1. Please correct the \
                    value {self.eway_bill_limit}")
        min_days_to_keep = 30
        self.sort_single_field_child("auto_deletion_policy_for_files", "document_type")
        self.sort_single_field_child("roles_allow_pub_att", "role")
        self.sort_single_field_child("docs_with_pub_att", "document_type")
        self.sort_single_field_child("auto_delete_from_version", "document_type")
        self.sort_single_field_child("bg_submit_cancel_docs", "document_type")
        for d in self.auto_deletion_policy_for_files:
            if flt(d.days_to_keep) < min_days_to_keep:
                frappe.throw(f"Minimum {min_days_to_keep} Days is Needed to Keep Files")

    def sort_single_field_child(self, table_name, field_name):
        sorted_table = []
        row_dict = {}
        idx = 1
        for row in self.get(table_name):
            print(row.__dict__)
            row_dict = row.__dict__
            del(row_dict["idx"])
            sorted_table.append(row_dict.copy())
        sorted_table = sorted(sorted_table, key=lambda i: i[field_name], reverse=0)
        self.set(table_name, [])
        for d in sorted_table:
            d["idx"] = idx
            idx += 1
            self.append(table_name, d)

    def update_cert(self):
        import base64

        result = run_openssl_commands(
            country=frappe.db.get_value('Country', self.pfx_country, 'code').upper(),
            state=self.pfx_state,
            locality=self.pfx_locality,
            organization=self.pfx_organization,
            common_name=self.pfx_common_name,
            email=self.pfx_email,
            gstin=self.gstin,
            password=self.tax_pro_password
        )

        for field, path in result.items():
            with open(f'/tmp/{path}', 'rb') as f:
                content = base64.b64encode(f.read())

            file_doc = frappe.get_doc({
                'doctype': 'File',
                'file_name': f'{today()}-{os.path.basename(path)}',
                'attached_to_doctype': self.doctype,
                'attached_to_name': self.name,
                'attached_to_field': field,
                'folder': 'Home/Attachments',
                'is_private': True,
                'content': content,
                'decode': True
            }).save()
            setattr(self, field, file_doc.file_url)
        self.save()


def generate_openssl_config(
    country: str,
    state: str,
    locality: str,
    organization: str,
    gstin: str,
    email: str,
    common_name: str) -> str:

    from tempfile import NamedTemporaryFile

    template = f'''
[req]
default_bits       = 2048
distinguished_name = req_distinguished_name
x509_extensions    = v3_req
prompt             = no

[req_distinguished_name]
C  = {country}
ST = {state}
L  = {locality}
O  = {organization}
OU = {gstin}
CN = {common_name}
emailAddress = {email}

[v3_req]
keyUsage = keyEncipherment, dataEncipherment
extendedKeyUsage = serverAuth'''

    tmp_config = NamedTemporaryFile(delete=False, suffix='.cnf', mode='w')
    tmp_config.write(template)
    tmp_config.close()

    return tmp_config.name


def run_openssl_commands(
    country: str,
    state: str,
    locality: str,
    organization: str,
    gstin: str,
    common_name: str,
    email: str,
    password: str,
    key_file: str = 'AspDsc.key',
    cert_file: str = 'AspDsc.cer',
    pfx_file: str = 'AspDsc.pfx'):

    import subprocess

    config_path = generate_openssl_config(
        country=country,
        state=state,
        locality=locality,
        organization=organization,
        common_name=common_name,
        email=email,
        gstin=gstin
    )

    subprocess.run([
        'openssl', 'req', '-x509', '-nodes', '-sha256', '-days', '3650',
        '-newkey', 'rsa:2048', 
        '-keyout', key_file,
        '-out', cert_file,
        '-config', config_path
    ], cwd='/tmp', check=True)

    subprocess.run([
            "openssl", "pkcs12", "-export",
            "-in", cert_file,
            "-inkey", key_file,
            "-CSP", "Microsoft Enhanced RSA and AES Cryptographic Provider",
            "-out", pfx_file,
            "-password", f"pass:{password}" 
    ], cwd='/tmp', check=True)


    return {
        'cert_priv_key': key_file,
        'cert_file': cert_file,
        'cert_pfx': pfx_file
    }
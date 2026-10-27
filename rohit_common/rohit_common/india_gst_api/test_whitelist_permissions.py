#  Copyright (c) 2026. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
"""
Guard (issue #15): v13 run_doc_method checks only read permission before it runs a
whitelisted Document method. So each such method must check permission itself, or a
user with read access can create or cancel an e-Way Bill on the GST system.

Run: bench --site dev-rb-v12 run-tests --module rohit_common.rohit_common.india_gst_api.test_whitelist_permissions
"""
import ast
import os
import unittest

APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCANNED = ("rohit_common/doctype", "rohit_common/india_gst_api")
PERMISSION_CALLS = ("check_permission", "has_permission", "only_for")


def _is_whitelist(decorator):
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    return isinstance(target, ast.Attribute) and target.attr == "whitelist"


def _calls_permission_check(fn):
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in PERMISSION_CALLS:
            return True
    return False


class TestWhitelistPermissions(unittest.TestCase):
    def test_whitelisted_document_methods_check_permission(self):
        misses = []
        for folder in SCANNED:
            for root, _dirs, files in os.walk(os.path.join(APP_DIR, folder)):
                for name in files:
                    if not name.endswith(".py") or name.startswith("test_"):
                        continue
                    path = os.path.join(root, name)
                    tree = ast.parse(open(path, encoding="utf-8").read())
                    for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
                        for fn in (n for n in cls.body if isinstance(n, ast.FunctionDef)):
                            if any(_is_whitelist(d) for d in fn.decorator_list) and not _calls_permission_check(fn):
                                misses.append(f"{os.path.relpath(path, APP_DIR)}:{fn.lineno} {cls.name}.{fn.name}")
        self.assertEqual(misses, [], "Whitelisted methods without a permission check:\n" + "\n".join(misses))


if __name__ == "__main__":
    unittest.main()

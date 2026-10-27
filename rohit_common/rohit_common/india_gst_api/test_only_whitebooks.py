#  Copyright (c) 2026. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
"""
Guard (issue #19): e-Invoice and e-Way Bill use only WhiteBooks. Fails if code
in the app sends the Charteredinfo/TaxPro credentials or URL pattern again.

Run: bench --site dev-rb-v12 run-tests --module rohit_common.rohit_common.india_gst_api.test_only_whitebooks
"""
import os
import re
import unittest

APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCANNED = ("rohit_common/india_gst_api", "rohit_common/doctype", "rohit_common/scheduled_tasks",
           "rohit_common/validations", "utils")
# Code that sends these is talking to Charteredinfo/TaxPro
FORBIDDEN = re.compile(r"aspid=|einvapi\.|tax_pro_|\bapi_link\b|sandbox_api_link|AuthToken=|ewbpwd=")
# Tests are skipped: they hold such URLs as fixtures, to prove they are not logged.
# patches/ is not scanned: its cutover patch names the old fields to delete them.


class TestOnlyWhiteBooks(unittest.TestCase):
    def test_no_charteredinfo_markers_in_code(self):
        hits = []
        for folder in SCANNED:
            for root, _dirs, files in os.walk(os.path.join(APP_DIR, folder)):
                for name in files:
                    if not name.endswith((".py", ".js")) or name.startswith("test_"):
                        continue
                    path = os.path.join(root, name)
                    for lineno, line in enumerate(open(path, encoding="utf-8"), 1):
                        if FORBIDDEN.search(line):
                            hits.append(f"{os.path.relpath(path, APP_DIR)}:{lineno}: {line.strip()}")
        self.assertEqual(hits, [], "Charteredinfo code is back:\n" + "\n".join(hits))


if __name__ == "__main__":
    unittest.main()

#  Copyright (c) 2026. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
"""
Unit tests for eway_bill_api.py on WhiteBooks (issue #19): the action, body and
params of each call, the "already generated" (604) path, and that each function
returns the unwrapped data. whitebooks_provider.eway_request is mocked; the
session and envelope are tested in test_whitebooks_provider.py.

Run: bench --site dev-rb-v12 run-tests --module rohit_common.rohit_common.india_gst_api.test_whitebooks_eway
"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from rohit_common.rohit_common.india_gst_api import eway_bill_api

REQUEST = "rohit_common.rohit_common.india_gst_api.eway_bill_api.whitebooks_provider.eway_request"


def _ok(data):
    return {"status_cd": "1", "data": data}


class TestCreateEwb(unittest.TestCase):
    @patch(REQUEST)
    def test_posts_payload_to_genewaybill(self, mock_request):
        mock_request.return_value = _ok({"ewayBillNo": 331001234567, "ewayBillDate": "27/10/2026 10:00:00 AM"})

        reply = eway_bill_api.create_ewb_from_json({"docType": "INV", "docNo": "SINV-0001"})

        self.assertEqual(reply["ewayBillNo"], 331001234567)
        mock_request.assert_called_once_with("POST", "genewaybill",
                                             body={"docType": "INV", "docNo": "SINV-0001"})

    @patch(REQUEST)
    def test_already_generated_returns_the_existing_one(self, mock_request):
        mock_request.side_effect = [
            {"status_cd": "0", "error": {"message": '{"errorCodes":"604"}'}},
            _ok({"ewayBillNo": 331001234567}),
        ]

        reply = eway_bill_api.create_ewb_from_json({"docType": "INV", "docNo": "SINV-0001"})

        self.assertEqual(reply["ewayBillNo"], 331001234567)
        self.assertEqual(mock_request.call_args.args, ("GET", "getewaybillgeneratedbyconsigner"))
        self.assertEqual(mock_request.call_args.kwargs["params"], {"docType": "INV", "docNo": "SINV-0001"})


class TestCancelEwb(unittest.TestCase):
    @patch(REQUEST)
    def test_posts_ewb_no_reason_and_short_remark(self, mock_request):
        mock_request.return_value = _ok({"ewayBillNo": 331001234567, "cancelDate": "27/10/2026"})

        eway_bill_api.cancel_ewb("331001234567", remark="x" * 80)

        body = mock_request.call_args.kwargs["body"]
        self.assertEqual(mock_request.call_args.args, ("POST", "canewb"))
        self.assertEqual((body["ewbNo"], body["cancelRsnCode"]), (331001234567, eway_bill_api.CANCEL_REASON_OTHERS))
        self.assertEqual(len(body["cancelRmrk"]), 50)


class TestUpdatePartB(unittest.TestCase):
    @patch(REQUEST)
    def test_vehicle_row_becomes_the_vehewb_body(self, mock_request):
        mock_request.return_value = _ok({"vehUpdDate": "27/10/2026", "validUpto": "28/10/2026 11:59:00 PM"})
        vehicle = SimpleNamespace(vehicle_number="HR55AB1234", mode_of_transport="Road", from_place="Faridabad",
                                  from_state_number=6, transport_doc_no=None, transport_doc_date=None)
        ewb_doc = SimpleNamespace(eway_bill_no="331001234567", vehicles=[vehicle])

        reply = eway_bill_api.update_partb_ewb(ewb_doc)

        self.assertEqual(reply["validUpto"], "28/10/2026 11:59:00 PM")
        self.assertEqual(mock_request.call_args.args, ("POST", "vehewb"))
        self.assertEqual(mock_request.call_args.kwargs["body"], {
            "ewbNo": 331001234567, "vehicleNo": "HR55AB1234", "transMode": "1", "fromPlace": "Faridabad",
            "fromState": 6, "reasonRem": "First Time", "reasonCode": "4"})


class TestLookups(unittest.TestCase):
    @patch(REQUEST)
    def test_get_eway_bill_details(self, mock_request):
        mock_request.return_value = _ok('{"ewbNo": 331001234567}')

        self.assertEqual(eway_bill_api.get_eway_bill_details("331001234567"), {"ewbNo": 331001234567})
        mock_request.assert_called_once_with("GET", "getewaybill", params={"ewbNo": "331001234567"})

    @patch(REQUEST)
    def test_pull_by_date_returns_a_list(self, mock_request):
        mock_request.return_value = _ok('[{"ewbNo": 1}, {"ewbNo": 2}]')

        self.assertEqual(eway_bill_api.get_ewb_date("26/10/2026"), [{"ewbNo": 1}, {"ewbNo": 2}])
        mock_request.assert_called_once_with("GET", "getewaybillsbydate", params={"date": "26/10/2026"})

    @patch(REQUEST)
    def test_pull_others_uses_the_other_party_action(self, mock_request):
        mock_request.return_value = _ok([])

        self.assertEqual(eway_bill_api.get_ewb_others("26/10/2026"), [])
        self.assertEqual(mock_request.call_args.args, ("GET", "getewaybillsofotherparty"))


if __name__ == "__main__":
    unittest.main()

from unittest.mock import MagicMock, patch

import requests

from odoo.tests import TransactionCase, tagged

from ..models import webhook_event as we


@tagged("post_install", "-at_install", "moviraider_dgt")
class TestWebhookOutbox(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        P = cls.env["product.product"]
        cls.scooter = P.create({"name": "Patinete", "is_scooter": True, "list_price": 500, "type": "consu"})
        cls.pack = P.create({"name": "Pack legal", "is_legal_pack": True, "list_price": 57, "type": "service"})
        cls.partner = cls.env["res.partner"].create(
            {"name": "Ana Test", "email": "ana@example.com", "mobile": "+34600111222"}
        )
        order = cls.env["sale.order"].create(
            {
                "partner_id": cls.partner.id,
                "order_line": [(0, 0, {"product_id": p.id, "product_uom_qty": 1}) for p in (cls.scooter, cls.pack)],
            }
        )
        order.action_confirm()
        cls.case = order.dgt_case_ids
        cls.event = cls.env["dgt.webhook.event"].search([("case_id", "=", cls.case.id)])

    def test_event_created_with_case_in_same_transaction(self):
        self.assertEqual(len(self.event), 1)
        self.assertEqual(self.event.event_type, "case.created")
        self.assertEqual(self.event.state, "pending")

    def test_payload_contract(self):
        p = self.event.payload
        self.assertEqual(p["event"], "case.created")
        self.assertEqual(p["case"]["reference"], self.case.name)
        self.assertEqual(p["contact"]["name"], "Ana Test")
        self.assertEqual(p["contact"]["phone"], "+34600111222")
        self.assertIn("/my/dgt/%s?access_token=" % self.case.id, p["case"]["portal_url"])

    def test_transitions_emit_events(self):
        self.case.write({"owner_vat": "12345678Z", "serial_number": "ABC-123456", "consent_gestoria": True})
        self.case.action_submit_data()
        self.case.action_validate()
        types = self.env["dgt.webhook.event"].search([("case_id", "=", self.case.id)], order="id").mapped("event_type")
        self.assertEqual(types, ["case.created", "case.data_received", "case.validated"])

    def test_delivery_success(self):
        ok = MagicMock()
        ok.raise_for_status.return_value = None
        with patch.object(we.requests, "post", return_value=ok) as post:
            self.event._deliver()
        self.assertEqual(self.event.state, "sent")
        self.assertTrue(self.event.sent_date)
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["event_id"], self.event.event_id)  # clave de idempotencia

    def test_delivery_failure_retries_then_fails(self):
        with patch.object(we.requests, "post", side_effect=requests.ConnectionError("down")):
            for i in range(1, we.MAX_ATTEMPTS):
                self.event._deliver()
                self.assertEqual(self.event.state, "pending")
                self.assertEqual(self.event.attempts, i)
            self.event._deliver()
        self.assertEqual(self.event.state, "failed")
        self.assertIn("down", self.event.last_error)

    def test_retry_after_failure(self):
        self.event.write({"state": "failed", "attempts": we.MAX_ATTEMPTS})
        ok = MagicMock()
        ok.raise_for_status.return_value = None
        with patch.object(we.requests, "post", return_value=ok):
            self.event.action_retry()
        self.assertEqual(self.event.state, "sent")

    def test_cron_only_picks_pending(self):
        self.event.state = "failed"
        with patch.object(we.requests, "post") as post:
            self.env["dgt.webhook.event"]._cron_dispatch()
        post.assert_not_called()

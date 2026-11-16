from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install", "moviraider_dgt")
class TestDgtPortal(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        P = cls.env["product.product"]
        scooter = P.create({"name": "Patinete", "is_scooter": True, "list_price": 500, "type": "consu"})
        pack = P.create({"name": "Pack legal", "is_legal_pack": True, "list_price": 57, "type": "service"})
        partner = cls.env["res.partner"].create({"name": "Luis Test"})
        order = cls.env["sale.order"].create(
            {
                "partner_id": partner.id,
                "order_line": [(0, 0, {"product_id": p.id, "product_uom_qty": 1}) for p in (scooter, pack)],
            }
        )
        order.action_confirm()
        cls.case = order.dgt_case_ids
        cls.token = cls.case._portal_ensure_token()

    def _url(self, token=None):
        return "/my/dgt/%s?access_token=%s" % (self.case.id, token or self.token)

    def test_get_with_valid_token(self):
        res = self.url_open(self._url())
        self.assertEqual(res.status_code, 200)
        self.assertIn("Nº de serie", res.text)

    def test_wrong_token_is_404(self):
        self.assertEqual(self.url_open(self._url("nope")).status_code, 404)

    def test_no_token_is_404(self):
        self.assertEqual(self.url_open("/my/dgt/%s" % self.case.id).status_code, 404)

    def test_submit_moves_case_to_received(self):
        res = self.url_open(
            self._url(),
            data={"owner_vat": "12345678z", "serial_number": "ABC-123456",
                  "consent_gestoria": "on", "csrf_token": self._csrf()},
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("Hemos recibido tus datos", res.text)
        self.case.invalidate_recordset()
        self.assertEqual(self.case.state, "received")
        self.assertEqual(self.case.owner_vat, "12345678Z")

    def test_invalid_serial_shows_error_and_keeps_pending(self):
        res = self.url_open(
            self._url(),
            data={"owner_vat": "12345678Z", "serial_number": "ab",
                  "consent_gestoria": "on", "csrf_token": self._csrf()},
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("6 y 25", res.text)
        self.case.invalidate_recordset()
        self.assertEqual(self.case.state, "pending")

    def test_submit_without_consent_is_rejected(self):
        res = self.url_open(
            self._url(),
            data={"owner_vat": "12345678Z", "serial_number": "ABC-123456",
                  "csrf_token": self._csrf()},
        )
        self.assertIn("Consentimiento", res.text)
        self.case.invalidate_recordset()
        self.assertEqual(self.case.state, "pending")

    def _csrf(self):
        from odoo.http import Request
        # Obtiene un token CSRF válido de la sesión de test.
        res = self.url_open(self._url())
        import re
        return re.search(r'name="csrf_token" value="([^"]+)"', res.text).group(1)

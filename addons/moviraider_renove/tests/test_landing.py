import re

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install", "moviraider_renove")
class TestLanding(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        P = cls.env["product.product"]
        cls.legacy = P.create({"name": "Kukirin G2 Pro (2022)", "is_scooter": True, "has_dgt_certificate": False,
                               "list_price": 700, "type": "consu"})
        cls.modern = P.create({"name": "Ecoxtrem M41 PRO", "is_scooter": True, "has_dgt_certificate": True,
                               "list_price": 847, "type": "consu"})
        cls.campaign = cls.env["renove.campaign"].create({"name": "Landing Test"})
        cls.campaign.utm_campaign_id = cls.env["utm.campaign"].create({"name": "landing-test"})
        cls.campaign.state = "running"

    def _csrf(self):
        return re.search(r'name="csrf_token" value="([^"]+)"', self.url_open("/renove").text).group(1)

    def _reserve(self, **data):
        payload = {"name": "Ana", "contact": "ana@example.com", "store": "Sevilla Central",
                   "model": "Kukirin G2 Pro (2022)", "consent": "on", "csrf_token": self._csrf()}
        payload.update(data)
        payload = {k: v for k, v in payload.items() if v is not None}
        return self.url_open("/renove/reserva", data=payload)

    def test_landing_is_public_and_lists_models(self):
        res = self.url_open("/renove")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Kukirin G2 Pro (2022)", res.text)  # datalist del buscador

    def test_legacy_model_expires(self):
        res = self.url_open("/renove?model=Kukirin+G2+Pro+(2022)")
        self.assertIn("no consta con certificado", res.text)

    def test_certified_model_is_ok(self):
        res = self.url_open("/renove?model=Ecoxtrem+M41+PRO")
        self.assertIn("consta con certificado de circulación", res.text)
        self.assertNotIn("no consta con certificado", res.text)

    def test_search_ignores_case_and_accents(self):
        res = self.url_open("/renove?model=kukirin+g2+pro+(2022)")
        self.assertIn("no consta con certificado", res.text)

    def test_unknown_model_is_neutral_not_an_error(self):
        res = self.url_open("/renove?model=Marca+Inventada+9000")
        self.assertEqual(res.status_code, 200)
        self.assertIn("No reconocemos ese modelo", res.text)

    def test_shop_link_keeps_campaign_attribution(self):
        res = self.url_open("/renove?model=Kukirin+G2+Pro+(2022)")
        self.assertIn("utm_campaign=landing-test", res.text)

    def test_store_preselected_from_qr(self):
        res = self.url_open("/renove?store=Toledo+Yuncos")
        self.assertRegex(res.text, r'value="Toledo Yuncos"\s+selected')

    def test_reservation_creates_request_linked_to_campaign(self):
        res = self._reserve()
        self.assertIn("Recibido", res.text)
        req = self.env["renove.request"].search([("contact", "=", "ana@example.com")])
        self.assertEqual(len(req), 1)
        self.assertEqual(req.campaign_id, self.campaign)
        self.assertEqual(req.product_tmpl_id.name, self.legacy.name)  # por nombre: la base puede tener otro igual
        self.assertEqual(req.state, "new")
        self.campaign.invalidate_recordset()
        self.assertEqual(self.campaign.request_count, 1)

    def test_reservation_without_consent_is_rejected(self):
        res = self._reserve(consent=None, contact="sin-consent@example.com")
        self.assertIn("aceptes", res.text)
        self.assertFalse(self.env["renove.request"].search([("contact", "=", "sin-consent@example.com")]))

    def test_reservation_with_invalid_store_is_rejected(self):
        res = self._reserve(store="Tienda Fantasma", contact="fantasma@example.com")
        self.assertIn("Elige la tienda", res.text)
        self.assertFalse(self.env["renove.request"].search([("contact", "=", "fantasma@example.com")]))

    def test_unknown_model_can_still_book_a_visit(self):
        self._reserve(model="Patinete Raro 3000", contact="raro@example.com")
        req = self.env["renove.request"].search([("contact", "=", "raro@example.com")])
        self.assertEqual(req.model_text, "Patinete Raro 3000")
        self.assertFalse(req.product_tmpl_id)  # no reconocido, pero el dato queda

    def test_homepage_shows_renove_hero(self):
        self.assertIn("Plan Renove", self.url_open("/").text)

    def test_coupon_wording_on_landing_and_homepage(self):
        self.env["renove.campaign"].search([("id", "!=", self.campaign.id), ("state", "=", "running")]).write({"state": "done"})
        self.campaign.discount_code = "CUPONTEST"
        self.campaign._sync_loyalty_program()
        for url in ("/renove", "/"):
            text = self.url_open(url).text
            self.assertIn("CUPONTEST", text, url)
            self.assertIn("en tu próxima compra", text, url)
            self.assertIn("10 % de descuento", text, url)
            self.assertIn("No incluye el pack legal", text, url)

    def test_january_22_clarification_matches_dgt_and_cites_source(self):
        text = self.url_open("/renove").text
        self.assertIn("21 de enero de 2024", text)   # fin de la comercialización sin certificado
        self.assertIn("22 de enero de 2027", text)   # fin del periodo transitorio
        self.assertIn("Vehículo no certificado", text)
        self.assertIn("dgt.es/nuestros-servicios/tu-vehiculo/vehiculos-de-movilidad-personal-vmp", text)

    def test_dgt_origin_is_explicit_everywhere_it_matters(self):
        """El mensaje debe dejar claro que es una norma de la DGT, no una promoción."""
        self.assertIn("NORMATIVA DGT", self.url_open("/shop").text)          # barra superior
        for url in ("/", "/renove"):
            text = self.url_open(url).text
            self.assertIn("Según la DGT", text, url)
            self.assertIn("solo podrán circular", text, url)

    def test_announcement_bar_on_other_pages_but_not_on_landing(self):
        self.assertIn("rn-bar", self.url_open("/shop").text)
        self.assertNotIn('class="rn-bar"', self.url_open("/renove").text)

    def test_homepage_lists_certified_scooters(self):
        self.modern.product_tmpl_id.write({"is_published": True, "website_published": True})
        self.assertIn("Ecoxtrem M41 PRO", self.url_open("/").text)

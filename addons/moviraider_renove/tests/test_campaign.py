from datetime import date, datetime, timedelta

from odoo.exceptions import UserError
from odoo.tests import HttpCase, TransactionCase, tagged


class RenoveCommon:
    @classmethod
    def _setup_catalog(cls):
        P = cls.env["product.product"]
        cls.legacy = P.create({"name": "Kukirin G2 (2022)", "is_scooter": True, "has_dgt_certificate": False,
                               "list_price": 700, "type": "consu"})
        cls.legacy2 = P.create({"name": "Joyor S5 (2021)", "is_scooter": True, "has_dgt_certificate": False,
                                "list_price": 500, "type": "consu"})
        cls.certified_old = P.create({"name": "Joyor X5S (2023, con cert.)", "is_scooter": True,
                                      "has_dgt_certificate": True, "list_price": 650, "type": "consu"})
        cls.modern = P.create({"name": "Ecoxtrem M41 PRO", "is_scooter": True, "has_dgt_certificate": True,
                               "list_price": 847, "type": "consu"})
        cls.helmet = P.create({"name": "Casco", "list_price": 30, "type": "consu"})

    @classmethod
    def _partner(cls, name, email=True, consent=True):
        return cls.env["res.partner"].create(
            {"name": name, "email": ("%s@example.com" % name.split()[0].lower()) if email else False,
             "marketing_consent": consent}
        )

    @classmethod
    def _sale(cls, partner, product, when, state="sale"):
        so = cls.env["sale.order"].create(
            {"partner_id": partner.id, "order_line": [(0, 0, {"product_id": product.id, "product_uom_qty": 1})]}
        )
        if state == "sale":
            so.action_confirm()
        so.date_order = when
        return so


@tagged("post_install", "-at_install", "moviraider_renove")
class TestSegmentation(RenoveCommon, TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_catalog()
        old, recent = datetime(2023, 5, 10), datetime(2025, 3, 3)
        cls.ok = cls._partner("Eva Contactable")
        cls._sale(cls.ok, cls.legacy, old)
        cls.two = cls._partner("Dos Patinetes")
        cls._sale(cls.two, cls.legacy, old)
        cls._sale(cls.two, cls.legacy2, datetime(2022, 7, 1))
        cls.renewed = cls._partner("Rafa Renovado")
        cls._sale(cls.renewed, cls.legacy, old)
        cls._sale(cls.renewed, cls.modern, recent)
        cls.no_consent = cls._partner("Nora SinConsent", consent=False)
        cls._sale(cls.no_consent, cls.legacy, old)
        cls.no_email = cls._partner("Hugo SinEmail", email=False)
        cls._sale(cls.no_email, cls.legacy, old)
        cls.had_cert = cls._partner("Celia ConCert")
        cls._sale(cls.had_cert, cls.certified_old, old)       # certificado: fuera del segmento
        cls.bought_modern = cls._partner("Marco Moderno")
        cls._sale(cls.bought_modern, cls.modern, recent)       # posterior al corte: fuera
        cls.draft_only = cls._partner("Dani Borrador")
        cls._sale(cls.draft_only, cls.legacy, old, state="draft")  # no confirmado: fuera
        cls.campaign = cls.env["renove.campaign"].create({"name": "Test Renove"})
        cls.campaign.action_compute_segment()

    def _line(self, partner):
        return self.campaign.line_ids.filtered(lambda l: l.partner_id == partner)

    def test_statuses(self):
        self.assertEqual(self._line(self.ok).status, "eligible")
        self.assertEqual(self._line(self.renewed).status, "renewed")
        self.assertEqual(self._line(self.no_consent).status, "no_consent")
        self.assertEqual(self._line(self.no_email).status, "no_contact")

    def test_excluded_customers_have_no_line(self):
        for p in (self.had_cert, self.bought_modern, self.draft_only):
            self.assertFalse(self._line(p), p.name)

    def test_one_line_per_partner_with_all_legacy_models(self):
        line = self._line(self.two)
        self.assertEqual(len(line), 1)
        self.assertEqual(line.legacy_product_ids, self.legacy | self.legacy2)
        self.assertEqual(line.last_legacy_date, date(2023, 5, 10))

    def _mine(self):
        """Solo los clientes creados por este test: el resultado no depende de
        que la base tenga ya otros datos (p. ej. el seed de la demo)."""
        mine = (self.ok | self.two | self.renewed | self.no_consent | self.no_email
                | self.had_cert | self.bought_modern | self.draft_only)
        return self.campaign.line_ids.filtered(lambda l: l.partner_id in mine)

    def test_funnel_counts(self):
        counts = {}
        for line in self._mine():
            counts[line.status] = counts.get(line.status, 0) + 1
        self.assertEqual(
            counts, {"eligible": 2, "no_consent": 1, "no_contact": 1, "renewed": 1}
        )

    def test_recompute_is_idempotent(self):
        before = len(self.campaign.line_ids)
        self.campaign.action_compute_segment()
        self.assertEqual(len(self.campaign.line_ids), before)

    def test_cutoff_is_configurable(self):
        self.campaign.cutoff_date = date(2023, 1, 1)  # solo cuentan compras de 2022 o antes
        self.campaign.action_compute_segment()
        partners = self._mine().partner_id
        self.assertEqual(partners, self.two)  # la única con una compra de 2022

    def test_days_left(self):
        today = date.today()
        self.campaign.deadline = today + timedelta(days=10)
        self.assertEqual(self.campaign.days_left, 10)
        self.campaign.deadline = today - timedelta(days=3)
        self.assertEqual(self.campaign.days_left, 0)  # nunca negativo


@tagged("post_install", "-at_install", "moviraider_renove")
class TestMailingAndAttribution(RenoveCommon, TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_catalog()
        cls.eva = cls._partner("Eva Contactable")
        cls._sale(cls.eva, cls.legacy, datetime(2023, 5, 10))
        cls.campaign = cls.env["renove.campaign"].create({"name": "Test Attribution", "discount_code": "TESTATTR"})
        cls.campaign.action_compute_segment()

    def test_prepare_mailing_targets_only_eligible(self):
        self.campaign.action_prepare_mailing()
        mailing = self.campaign.mailing_id
        self.assertTrue(mailing)
        self.assertEqual(mailing.state, "draft")  # nunca se envía solo
        self.assertEqual(mailing.campaign_id, self.campaign.utm_campaign_id)
        self.assertEqual(self.campaign.state, "running")
        self.assertIn(self.eva.id, self.env["res.partner"].search(eval(mailing.mailing_domain)).ids)

    def test_prepare_mailing_requires_eligible(self):
        empty = self.env["renove.campaign"].create({"name": "Vacía", "cutoff_date": date(2000, 1, 1)})
        with self.assertRaises(UserError):
            empty.action_prepare_mailing()

    def test_attributed_order_counts_as_conversion(self):
        self.campaign.action_prepare_mailing()
        utm = self.campaign.utm_campaign_id
        so = self._sale(self.eva, self.modern, datetime.now())
        self.assertEqual(self.campaign.converted_count, 0)  # sin atribución no cuenta
        so.campaign_id = utm
        self.campaign.invalidate_recordset()
        self.assertEqual(self.campaign.converted_count, 1)
        self.assertEqual(self.campaign.revenue, so.amount_untaxed)

    def test_draft_order_is_not_a_conversion(self):
        self.campaign.action_prepare_mailing()
        so = self._sale(self.eva, self.modern, datetime.now(), state="draft")
        so.campaign_id = self.campaign.utm_campaign_id
        self.campaign.invalidate_recordset()
        self.assertEqual(self.campaign.converted_count, 0)


@tagged("post_install", "-at_install", "moviraider_renove")
class TestWebAttribution(RenoveCommon, HttpCase):
    """Humo: ¿el carrito web hereda la campaña desde el enlace del correo?"""

    def test_cart_inherits_utm_campaign(self):
        if "website_sale" not in self.env["ir.module.module"].search([("state", "=", "installed")]).mapped("name"):
            self.skipTest("website_sale no instalado")
        self._setup_catalog()
        self.modern.product_tmpl_id.write({"is_published": True, "website_published": True})
        campaign = self.env["renove.campaign"].create({"name": "Campaña Web Test"})
        utm = self.env["utm.campaign"].create({"name": "campania-web-test"})
        campaign.utm_campaign_id = utm
        self.url_open("/shop?utm_campaign=%s" % utm.name)
        res = self.url_open(
            "/shop/cart/update_json",
            data=__import__("json").dumps({"jsonrpc": "2.0", "method": "call",
                                           "params": {"product_id": self.modern.id, "add_qty": 1}}),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(res.status_code, 200)
        order = self.env["sale.order"].search([], order="id desc", limit=1)
        self.assertEqual(order.campaign_id, utm, "el pedido web no heredó la campaña UTM")

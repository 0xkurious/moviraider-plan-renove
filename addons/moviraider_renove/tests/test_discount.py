import json
from datetime import date, datetime, timedelta

from odoo.tests import HttpCase, TransactionCase, tagged


def apply_code(order, code):
    """Replica lo que hace la tienda al introducir un código en el carrito."""
    status = order._try_apply_code(code)
    if "error" in status:
        return status
    coupon, rewards = next(iter(status.items()))
    order._apply_program_reward(rewards[:1], coupon)
    order._update_programs_and_rewards()
    return {}


@tagged("post_install", "-at_install", "moviraider_renove")
class TestDiscount(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        P = cls.env["product.product"]
        cls.scooter = P.create({"name": "Patinete Dto", "is_scooter": True, "has_dgt_certificate": True,
                                "list_price": 1000, "type": "consu"})
        cls.pack = P.create({"name": "Pack legal Dto", "is_legal_pack": True, "list_price": 57, "type": "service"})
        cls.partner = cls.env["res.partner"].create({"name": "Cliente Dto"})
        cls.campaign = cls.env["renove.campaign"].create(
            {"name": "Dto Test", "discount_code": "TESTDTO10", "discount_percent": 10.0}
        )
        cls.campaign._sync_loyalty_program()

    def _order(self):
        return self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "order_line": [(0, 0, {"product_id": p.id, "product_uom_qty": 1}) for p in (self.scooter, self.pack)],
        })

    def test_program_is_created_from_campaign(self):
        prog = self.campaign.loyalty_program_id
        self.assertTrue(prog)
        self.assertEqual(prog.program_type, "promo_code")
        self.assertEqual(prog.date_to, self.campaign.deadline)  # caduca con la campaña
        self.assertEqual(prog.rule_ids.code, "TESTDTO10")
        self.assertEqual(prog.reward_ids.discount, 10.0)

    def test_code_discounts_the_scooter_only_not_the_legal_pack(self):
        order = self._order()
        self.assertEqual(order.amount_untaxed, 1057)
        self.assertEqual(apply_code(order, "TESTDTO10"), {})
        reward = order.order_line.filtered("is_reward_line")
        self.assertEqual(len(reward), 1)
        self.assertAlmostEqual(reward.price_subtotal, -100.0)          # 10 % de 1000, no de 1057
        self.assertAlmostEqual(order.amount_untaxed, 957.0)            # el pack (57) intacto

    def test_wrong_code_is_rejected(self):
        order = self._order()
        self.assertIn("error", apply_code(order, "NOEXISTE"))
        self.assertEqual(order.amount_untaxed, 1057)

    def test_code_cannot_be_applied_twice(self):
        order = self._order()
        apply_code(order, "TESTDTO10")
        self.assertIn("error", apply_code(order, "TESTDTO10"))
        self.assertEqual(len(order.order_line.filtered("is_reward_line")), 1)

    def test_code_expires_with_the_campaign(self):
        self.campaign.deadline = date.today() - timedelta(days=1)
        self.assertEqual(self.campaign.loyalty_program_id.date_to, date.today() - timedelta(days=1))
        order = self._order()
        self.assertIn("error", apply_code(order, "TESTDTO10"))
        self.assertEqual(order.amount_untaxed, 1057)

    def test_changing_percent_updates_the_program(self):
        self.campaign.discount_percent = 20.0
        self.assertEqual(self.campaign.loyalty_program_id.reward_ids.discount, 20.0)
        order = self._order()
        apply_code(order, "TESTDTO10")
        self.assertAlmostEqual(order.amount_untaxed, 857.0)

    def test_duplicate_code_gives_a_clear_error(self):
        from odoo.exceptions import UserError
        other = self.env["renove.campaign"].create({"name": "Otra", "discount_code": "TESTDTO10"})
        with self.assertRaises(UserError) as ctx:
            other._sync_loyalty_program()
        self.assertIn("ya lo usa", str(ctx.exception))

    def test_invalid_percent_is_rejected(self):
        from odoo.exceptions import UserError
        with self.assertRaises(UserError):
            self.campaign.discount_percent = 150

    def test_funnel_reports_discount_granted(self):
        self.campaign.utm_campaign_id = self.env["utm.campaign"].create({"name": "dto-test-utm"})
        order = self._order()
        apply_code(order, "TESTDTO10")
        order.campaign_id = self.campaign.utm_campaign_id
        order.action_confirm()
        order.date_order = datetime.now()
        self.campaign.invalidate_recordset()
        self.assertAlmostEqual(self.campaign.discount_total, 100.0)
        self.assertAlmostEqual(self.campaign.revenue, 957.0)

    def test_prepare_mailing_creates_the_working_code(self):
        P = self.env["product.product"]
        old = P.create({"name": "Antiguo Dto", "is_scooter": True, "has_dgt_certificate": False,
                        "list_price": 500, "type": "consu"})
        cust = self.env["res.partner"].create({"name": "Eva Dto", "email": "eva.dto@example.com",
                                               "marketing_consent": True})
        so = self.env["sale.order"].create({"partner_id": cust.id,
                                            "order_line": [(0, 0, {"product_id": old.id, "product_uom_qty": 1})]})
        so.action_confirm()
        so.date_order = datetime(2023, 5, 1)
        camp = self.env["renove.campaign"].create({"name": "Dto Mailing", "discount_code": "MAILDTO"})
        self.assertFalse(camp.loyalty_program_id)
        camp.action_prepare_mailing()
        self.assertTrue(camp.loyalty_program_id)
        self.assertIn("MAILDTO", camp.mailing_id.body_html)
        self.assertIn("en tu próxima compra", camp.mailing_id.body_html)
        self.assertIn("10 % de descuento", camp.mailing_id.body_html)


@tagged("post_install", "-at_install", "moviraider_renove")
class TestDiscountOnWebCart(HttpCase):
    def test_promo_code_in_the_real_web_cart(self):
        if "website_sale_loyalty" not in self.env["ir.module.module"].search([("state", "=", "installed")]).mapped("name"):
            self.skipTest("website_sale_loyalty no instalado")
        P = self.env["product.product"]
        scooter = P.create({"name": "Web Dto", "is_scooter": True, "has_dgt_certificate": True,
                            "list_price": 1000, "type": "consu"})
        scooter.product_tmpl_id.write({"is_published": True, "website_published": True})
        camp = self.env["renove.campaign"].create({"name": "Web Dto Camp", "discount_code": "WEBDTO"})
        camp._sync_loyalty_program()
        self.url_open("/shop")
        self.url_open("/shop/cart/update_json", data=json.dumps(
            {"jsonrpc": "2.0", "method": "call", "params": {"product_id": scooter.id, "add_qty": 1}}),
            headers={"Content-Type": "application/json"})
        order = self.env["sale.order"].search([], order="id desc", limit=1)
        self.assertEqual(order.amount_untaxed, 1000)
        self.url_open("/shop/pricelist?promo=WEBDTO")
        order.invalidate_recordset()
        self.assertAlmostEqual(order.amount_untaxed, 900.0, msg="el código no rebajó el carrito web")

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "moviraider_dgt")
class TestDgtCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Product = cls.env["product.product"]
        cls.scooter = Product.create(
            {"name": "Patinete test", "is_scooter": True, "has_dgt_certificate": True,
             "list_price": 600, "type": "consu"}
        )
        cls.pack = Product.create(
            {"name": "Pack legal", "is_legal_pack": True, "list_price": 57, "type": "service"}
        )
        cls.accessory = Product.create({"name": "Casco", "list_price": 30, "type": "consu"})
        cls.partner = cls.env["res.partner"].create({"name": "Cliente Test"})

    def _order(self, *products, qty=1):
        return self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "order_line": [
                    (0, 0, {"product_id": p.id, "product_uom_qty": qty if p == self.pack else 1})
                    for p in products
                ],
            }
        )

    def _complete(self, case):
        case.write({"owner_vat": "12345678Z", "serial_number": "ABC-123456", "consent_gestoria": True})

    # --- creación al confirmar ---------------------------------------
    def test_case_created_on_confirm_with_pack(self):
        order = self._order(self.scooter, self.pack)
        self.assertFalse(order.dgt_case_ids)
        order.action_confirm()
        self.assertEqual(len(order.dgt_case_ids), 1)
        case = order.dgt_case_ids
        self.assertEqual(case.state, "pending")
        self.assertEqual(case.scooter_id, self.scooter)
        self.assertTrue(case.name.startswith("DGT/"))

    def test_no_case_without_pack(self):
        order = self._order(self.scooter, self.accessory)
        order.action_confirm()
        self.assertFalse(order.dgt_case_ids)

    def test_one_case_per_pack_unit(self):
        order = self._order(self.scooter, self.pack, qty=2)
        order.action_confirm()
        self.assertEqual(len(order.dgt_case_ids), 2)

    def test_confirm_is_idempotent(self):
        order = self._order(self.scooter, self.pack)
        order.action_confirm()
        order._create_dgt_cases()
        self.assertEqual(len(order.dgt_case_ids), 1)

    # --- transiciones -------------------------------------------------
    def test_happy_path(self):
        order = self._order(self.scooter, self.pack)
        order.action_confirm()
        case = order.dgt_case_ids
        self._complete(case)
        case.action_submit_data()
        self.assertEqual(case.state, "received")
        self.assertTrue(case.data_received_date)
        case.action_validate()
        case.action_send_gestoria()
        self.assertEqual(case.state, "sent")

    def test_cannot_submit_without_data(self):
        order = self._order(self.scooter, self.pack)
        order.action_confirm()
        with self.assertRaises(UserError):
            order.dgt_case_ids.action_submit_data()

    def test_cannot_skip_states(self):
        order = self._order(self.scooter, self.pack)
        order.action_confirm()
        case = order.dgt_case_ids
        with self.assertRaises(UserError):
            case.action_validate()
        with self.assertRaises(UserError):
            case.action_send_gestoria()

    def test_cannot_cancel_after_sent(self):
        order = self._order(self.scooter, self.pack)
        order.action_confirm()
        case = order.dgt_case_ids
        self._complete(case)
        case.action_submit_data()
        case.action_validate()
        case.action_send_gestoria()
        with self.assertRaises(UserError):
            case.action_cancel()

    def test_serial_format(self):
        order = self._order(self.scooter, self.pack)
        order.action_confirm()
        with self.assertRaises(ValidationError):
            order.dgt_case_ids.serial_number = "ab"

    def test_stalled_after_five_days(self):
        order = self._order(self.scooter, self.pack)
        order.action_confirm()
        case = order.dgt_case_ids
        self.assertFalse(case.is_stalled)
        self.env.cr.execute(
            "UPDATE dgt_case SET create_date = now() - interval '6 days' WHERE id = %s", (case.id,)
        )
        case.invalidate_recordset()
        self.assertTrue(case.is_stalled)
        self.assertEqual(case.days_open, 6)

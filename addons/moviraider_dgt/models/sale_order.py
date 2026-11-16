from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    dgt_case_ids = fields.One2many("dgt.case", "sale_order_id", string="Expedientes DGT")
    dgt_case_count = fields.Integer(compute="_compute_dgt_case_count")

    def _compute_dgt_case_count(self):
        for order in self:
            order.dgt_case_count = len(order.dgt_case_ids)

    def action_confirm(self):
        res = super().action_confirm()
        self._create_dgt_cases()
        return res

    def _create_dgt_cases(self):
        """Un expediente por unidad de pack legal. Idempotente por línea."""
        Case = self.env["dgt.case"]
        for order in self:
            scooter_lines = order.order_line.filtered(lambda l: l.product_id.is_scooter)
            scooter = scooter_lines[:1].product_id
            for line in order.order_line.filtered(lambda l: l.product_id.is_legal_pack):
                existing = Case.search_count([("sale_line_id", "=", line.id)])
                to_create = max(int(line.product_uom_qty) - existing, 0)
                for _i in range(to_create):
                    Case.create(
                        {
                            "sale_order_id": order.id,
                            "sale_line_id": line.id,
                            "scooter_id": scooter.id or False,
                        }
                    )

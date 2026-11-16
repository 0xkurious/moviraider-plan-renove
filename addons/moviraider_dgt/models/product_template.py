from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    is_legal_pack = fields.Boolean(
        string="Pack legal DGT",
        help="Si el producto se vende en un pedido, se abre un expediente DGT.",
    )

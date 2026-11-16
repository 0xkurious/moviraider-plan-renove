from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    is_scooter = fields.Boolean(string="Es patinete (VMP)")
    has_dgt_certificate = fields.Boolean(
        string="Con certificado DGT",
        help="Modelo con certificado de circulación (homologado).",
    )
    weight_kg = fields.Float(string="Peso (kg)")
    max_speed_kmh = fields.Float(string="Velocidad máx. (km/h)")

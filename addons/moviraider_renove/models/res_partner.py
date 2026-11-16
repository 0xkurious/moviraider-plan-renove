from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    marketing_consent = fields.Boolean(
        string="Consentimiento de marketing",
        help="Solo los clientes con consentimiento entran en el segmento contactable.",
    )

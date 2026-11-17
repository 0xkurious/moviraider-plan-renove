from odoo import fields, models

STORES = [
    "Sevilla Central",
    "Sevilla Este",
    "Sevilla Macarena",
    "Sevilla Plaza de Armas",
    "València",
    "Toledo Yuncos",
    "Lanzarote Arrecife",
]


class RenoveRequest(models.Model):
    """Solicitud de visita que llega desde la web pública.

    Es la vía para clientes que MoviRaider no conoce (patinete comprado en otro
    sitio): dejan el dato mínimo a cambio de que se lo revisen en tienda."""

    _name = "renove.request"
    _description = "Solicitud de visita Renove"
    _order = "id desc"

    name = fields.Char(string="Nombre", required=True)
    contact = fields.Char(string="Teléfono o email", required=True)
    model_text = fields.Char(string="Patinete (según el cliente)")
    product_tmpl_id = fields.Many2one("product.template", string="Modelo reconocido")
    store = fields.Selection([(s, s) for s in STORES], string="Tienda", required=True)
    campaign_id = fields.Many2one("renove.campaign", string="Campaña", index=True)
    consent = fields.Boolean(string="Acepta ser contactado")
    state = fields.Selection(
        [("new", "Nueva"), ("contacted", "Contactada"), ("done", "Atendida")],
        string="Estado",
        default="new",
    )
    created_at = fields.Datetime(string="Recibida", default=fields.Datetime.now, readonly=True)

    def action_contacted(self):
        self.state = "contacted"

    def action_done(self):
        self.state = "done"

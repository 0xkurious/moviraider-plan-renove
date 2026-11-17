from collections import defaultdict
from datetime import date, datetime, time

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class RenoveCampaign(models.Model):
    _name = "renove.campaign"
    _description = "Campaña Renove"
    _inherit = ["mail.thread"]

    name = fields.Char(string="Nombre", required=True, default="Plan Renove 2027", tracking=True)
    state = fields.Selection(
        [("draft", "Borrador"), ("running", "En marcha"), ("done", "Finalizada")],
        string="Estado",
        default="draft",
        tracking=True,
    )
    cutoff_date = fields.Date(
        string="Vendido antes de",
        default=date(2024, 1, 22),
        required=True,
        help="Supuesto: un patinete vendido antes de esta fecha no tiene certificado de circulación.",
    )
    deadline = fields.Date(string="Fin del periodo transitorio", default=date(2027, 1, 22), required=True)
    days_left = fields.Integer(string="Días restantes", compute="_compute_days_left")
    discount_code = fields.Char(string="Código de descuento", default="RENOVE27")
    offer_text = fields.Text(
        string="Texto de la oferta",
        default="A partir del 22 de enero de 2027 tu patinete ya no podrá circular. "
        "Cámbialo por un modelo homologado con un descuento exclusivo de cliente.",
    )

    utm_campaign_id = fields.Many2one("utm.campaign", string="Campaña UTM", readonly=True, copy=False)
    mailing_id = fields.Many2one("mailing.mailing", string="Correo", readonly=True, copy=False)
    line_ids = fields.One2many("renove.campaign.line", "campaign_id", string="Clientes")

    eligible_count = fields.Integer(string="Contactables", compute="_compute_funnel")
    no_consent_count = fields.Integer(string="Sin consentimiento", compute="_compute_funnel")
    no_contact_count = fields.Integer(string="Sin vía de contacto", compute="_compute_funnel")
    renewed_count = fields.Integer(string="Ya renovados", compute="_compute_funnel")
    converted_count = fields.Integer(string="Han comprado", compute="_compute_funnel")
    revenue = fields.Monetary(string="Ingresos atribuidos", compute="_compute_funnel", currency_field="currency_id")
    currency_id = fields.Many2one("res.currency", string="Moneda", default=lambda s: s.env.company.currency_id)

    @api.depends("deadline")
    def _compute_days_left(self):
        today = fields.Date.context_today(self)
        for c in self:
            c.days_left = max((c.deadline - today).days, 0) if c.deadline else 0

    # --- Embudo --------------------------------------------------------
    def _attributed_orders(self):
        self.ensure_one()
        if not self.utm_campaign_id:
            return self.env["sale.order"]
        return self.env["sale.order"].search(
            [("campaign_id", "=", self.utm_campaign_id.id), ("state", "=", "sale")]
        )

    @api.depends("line_ids.status", "utm_campaign_id")
    def _compute_funnel(self):
        for c in self:
            by_status = defaultdict(int)
            for line in c.line_ids:
                by_status[line.status] += 1
            c.eligible_count = by_status["eligible"]
            c.no_consent_count = by_status["no_consent"]
            c.no_contact_count = by_status["no_contact"]
            c.renewed_count = by_status["renewed"]
            orders = c._attributed_orders()
            c.converted_count = len(orders.partner_id)
            c.revenue = sum(orders.mapped("amount_untaxed"))

    # --- Segmentación --------------------------------------------------
    def _segment(self):
        """Devuelve {partner: (status, legacy_products, last_legacy_date)}.

        Reglas (cada una es un supuesto declarado en el README):
        - legado: patinete sin certificado en un pedido confirmado anterior al corte.
        - renovado: el cliente ya compró alguna vez un patinete con certificado.
        - sin vía de contacto: sin email.  - sin consentimiento: marketing_consent falso.
        """
        self.ensure_one()
        cutoff = datetime.combine(self.cutoff_date, time.min)
        Line = self.env["sale.order.line"]
        base = [("order_id.state", "=", "sale"), ("product_id.is_scooter", "=", True)]
        legacy = Line.search(
            base + [("product_id.has_dgt_certificate", "=", False), ("order_id.date_order", "<", cutoff)]
        )
        certified_partners = Line.search(
            base + [("product_id.has_dgt_certificate", "=", True)]
        ).order_id.partner_id

        products = defaultdict(lambda: self.env["product.product"])
        last_date = {}
        for sol in legacy:
            partner = sol.order_id.partner_id
            products[partner] |= sol.product_id
            d = sol.order_id.date_order.date()
            last_date[partner] = max(last_date.get(partner, d), d)

        result = {}
        for partner, prods in products.items():
            if partner in certified_partners:
                status = "renewed"
            elif not partner.email:
                status = "no_contact"
            elif not partner.marketing_consent:
                status = "no_consent"
            else:
                status = "eligible"
            result[partner] = (status, prods, last_date[partner])
        return result

    def action_compute_segment(self):
        for c in self:
            c.line_ids.unlink()
            vals = [
                {
                    "campaign_id": c.id,
                    "partner_id": partner.id,
                    "status": status,
                    "legacy_product_ids": [(6, 0, prods.ids)],
                    "last_legacy_date": last,
                }
                for partner, (status, prods, last) in c._segment().items()
            ]
            self.env["renove.campaign.line"].create(vals)

    # --- Correo y atribución ---------------------------------------------
    def action_prepare_mailing(self):
        """Crea la campaña UTM y un correo en borrador dirigido al segmento contactable.

        No se envía: lo lanza una persona. La atribución usa el mecanismo nativo
        de Odoo (utm.campaign -> sale.order.campaign_id)."""
        self.ensure_one()
        if not self.line_ids:
            self.action_compute_segment()
        eligible = self.line_ids.filtered(lambda l: l.status == "eligible").partner_id
        if not eligible:
            raise UserError(_("No hay clientes contactables en el segmento."))
        if not self.utm_campaign_id:
            self.utm_campaign_id = self.env["utm.campaign"].create({"name": self.name})
        body = self._mailing_body()
        vals = {
            "subject": _("Tu patinete deja de poder circular el %s", self.deadline.strftime("%d/%m/%Y")),
            "body_html": body,
            "mailing_model_id": self.env["ir.model"]._get_id("res.partner"),
            "mailing_domain": str([("id", "in", eligible.ids)]),
            "campaign_id": self.utm_campaign_id.id,
        }
        if self.mailing_id:
            self.mailing_id.write(vals)
        else:
            self.mailing_id = self.env["mailing.mailing"].create(vals)
        self.state = "running"

    def _mailing_body(self):
        self.ensure_one()
        shop = "%s/shop" % self.get_base_url()
        return (
            "<p>Hola {{ object.name }},</p>"
            "<p>%s</p>"
            "<p>Quedan <strong>%s días</strong>. Usa el código <strong>%s</strong>.</p>"
            '<p><a href="%s">Ver patinetes homologados</a></p>'
        ) % (self.offer_text, self.days_left, self.discount_code or "", shop)

    def action_view_orders(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Pedidos atribuidos"),
            "res_model": "sale.order",
            "view_mode": "list,form",
            "domain": [("id", "in", self._attributed_orders().ids)],
        }


class RenoveCampaignLine(models.Model):
    _name = "renove.campaign.line"
    _description = "Cliente en la campaña Renove"
    _order = "status, partner_id"

    campaign_id = fields.Many2one("renove.campaign", string="Campaña", required=True, ondelete="cascade", index=True)
    partner_id = fields.Many2one("res.partner", string="Cliente", required=True)
    status = fields.Selection(
        [
            ("eligible", "Contactable"),
            ("no_consent", "Sin consentimiento"),
            ("no_contact", "Sin vía de contacto"),
            ("renewed", "Ya renovado"),
        ],
        string="Estado",
        required=True,
        index=True,
    )
    legacy_product_ids = fields.Many2many("product.product", string="Patinete(s) antiguo(s)")
    last_legacy_date = fields.Date(string="Última compra antigua")
    email = fields.Char(related="partner_id.email", string="Email")
    converted = fields.Boolean(string="Ha comprado", compute="_compute_converted")

    def _compute_converted(self):
        for line in self:
            orders = line.campaign_id._attributed_orders()
            line.converted = line.partner_id in orders.partner_id

import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

SERIAL_RE = re.compile(r"^[A-Za-z0-9\-]{6,25}$")


class DgtCase(models.Model):
    _name = "dgt.case"
    _description = "Expediente DGT"
    _inherit = ["mail.thread", "portal.mixin"]
    _order = "create_date desc, id desc"

    name = fields.Char(string="Referencia", readonly=True, copy=False, default="Nuevo")
    state = fields.Selection(
        [
            ("pending", "Pendiente de datos"),
            ("received", "Datos recibidos"),
            ("validated", "Validado"),
            ("sent", "Enviado a gestoría"),
            ("cancel", "Cancelado"),
        ],
        string="Estado",
        default="pending",
        required=True,
        tracking=True,
        index=True,
    )
    sale_order_id = fields.Many2one("sale.order", string="Pedido", required=True, ondelete="cascade", index=True)
    sale_line_id = fields.Many2one("sale.order.line", string="Línea de pedido", ondelete="set null")
    partner_id = fields.Many2one(related="sale_order_id.partner_id", string="Cliente", store=True)
    scooter_id = fields.Many2one(
        "product.product", string="Patinete", domain=[("is_scooter", "=", True)]
    )

    # Datos que Odoo no conoce y pide al cliente.
    owner_vat = fields.Char(string="DNI/NIE del titular")
    serial_number = fields.Char(string="Nº de serie")
    consent_gestoria = fields.Boolean(
        string="Consentimiento para que la gestoría actúe en su nombre", tracking=True
    )
    data_received_date = fields.Datetime(string="Datos recibidos el", readonly=True)

    portal_url = fields.Char(compute="_compute_portal_url", string="Enlace para el cliente")
    days_open = fields.Integer(compute="_compute_days_open", string="Días abierto")
    is_stalled = fields.Boolean(compute="_compute_days_open", string="Parado")

    @api.depends("create_date", "write_date", "state")
    def _compute_days_open(self):
        """Días abierto: cuenta hasta hoy mientras el expediente está vivo y se
        congela (en la última escritura) cuando se envía o se cancela."""
        now = fields.Datetime.now()
        for case in self:
            start = case.create_date or now
            end = (case.write_date or now) if case.state in ("sent", "cancel") else now
            case.days_open = max((end - start).days, 0)
            case.is_stalled = case.state == "pending" and case.days_open >= 5

    def _compute_access_url(self):
        super()._compute_access_url()
        for case in self:
            case.access_url = "/my/dgt/%s" % case.id

    def _compute_portal_url(self):
        for case in self:
            if case.id:
                token = case.sudo()._portal_ensure_token()
                case.portal_url = "%s%s?access_token=%s" % (case.get_base_url(), case.access_url, token)
            else:
                case.portal_url = False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Nuevo") == "Nuevo":
                vals["name"] = self.env["ir.sequence"].next_by_code("dgt.case") or "Nuevo"
        cases = super().create(vals_list)
        cases._emit_event("case.created")
        return cases

    # --- Webhooks ------------------------------------------------------
    def _webhook_payload(self, event_type):
        self.ensure_one()
        partner = self.partner_id
        return {
            "event": event_type,
            "occurred_at": fields.Datetime.to_string(fields.Datetime.now()),
            "case": {
                "reference": self.name,
                "state": self.state,
                "order": self.sale_order_id.name,
                "scooter": self.scooter_id.display_name or None,
                "days_open": self.days_open,
                "portal_url": self.portal_url,
            },
            "contact": {
                "name": partner.name,
                "email": partner.email or None,
                "phone": partner.mobile or partner.phone or None,
            },
        }

    def _emit_event(self, event_type):
        Event = self.env["dgt.webhook.event"].sudo()
        for case in self:
            Event.create(
                {
                    "event_type": event_type,
                    "case_id": case.id,
                    "payload": case._webhook_payload(event_type),
                }
            )

    @api.constrains("serial_number")
    def _check_serial_format(self):
        for case in self:
            if case.serial_number and not SERIAL_RE.match(case.serial_number):
                raise ValidationError(
                    _("El nº de serie debe tener entre 6 y 25 caracteres alfanuméricos.")
                )

    # --- Transiciones -------------------------------------------------
    def _missing_fields(self):
        self.ensure_one()
        missing = []
        if not self.owner_vat:
            missing.append(_("DNI/NIE"))
        if not self.serial_number:
            missing.append(_("Nº de serie"))
        if not self.consent_gestoria:
            missing.append(_("Consentimiento"))
        return missing

    def action_submit_data(self):
        for case in self:
            if case.state != "pending":
                raise UserError(_("Solo se pueden enviar datos en un expediente pendiente."))
            missing = case._missing_fields()
            if missing:
                raise UserError(_("Faltan datos: %s", ", ".join(missing)))
            case.write({"state": "received", "data_received_date": fields.Datetime.now()})
            case._emit_event("case.data_received")

    def action_validate(self):
        for case in self:
            if case.state != "received":
                raise UserError(_("Solo se puede validar un expediente con datos recibidos."))
            case.state = "validated"
            case._emit_event("case.validated")

    def action_send_gestoria(self):
        for case in self:
            if case.state != "validated":
                raise UserError(_("Solo se envía a la gestoría un expediente validado."))
            case.state = "sent"
            case._emit_event("case.sent_to_gestoria")

    def action_cancel(self):
        for case in self:
            if case.state == "sent":
                raise UserError(_("Un expediente ya enviado no se puede cancelar."))
            case.state = "cancel"
            case._emit_event("case.cancelled")

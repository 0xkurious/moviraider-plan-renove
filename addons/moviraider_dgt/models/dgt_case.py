import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

SERIAL_RE = re.compile(r"^[A-Za-z0-9\-]{6,25}$")


class DgtCase(models.Model):
    _name = "dgt.case"
    _description = "Expediente DGT"
    _inherit = ["mail.thread"]
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
        default="pending",
        required=True,
        tracking=True,
        index=True,
    )
    sale_order_id = fields.Many2one("sale.order", required=True, ondelete="cascade", index=True)
    sale_line_id = fields.Many2one("sale.order.line", ondelete="set null")
    partner_id = fields.Many2one(related="sale_order_id.partner_id", store=True)
    scooter_id = fields.Many2one(
        "product.product", string="Patinete", domain=[("is_scooter", "=", True)]
    )

    # Datos que Odoo no conoce y pide al cliente.
    owner_vat = fields.Char(string="DNI/NIE del titular")
    serial_number = fields.Char(string="Nº de serie")
    consent_gestoria = fields.Boolean(
        string="Consentimiento para que la gestoría actúe en su nombre", tracking=True
    )
    data_received_date = fields.Datetime(readonly=True)

    days_open = fields.Integer(compute="_compute_days_open", string="Días abierto")
    is_stalled = fields.Boolean(compute="_compute_days_open", string="Parado")

    @api.depends("create_date", "state", "data_received_date")
    def _compute_days_open(self):
        now = fields.Datetime.now()
        for case in self:
            start = case.create_date or now
            case.days_open = (now - start).days
            case.is_stalled = case.state == "pending" and case.days_open >= 5

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Nuevo") == "Nuevo":
                vals["name"] = self.env["ir.sequence"].next_by_code("dgt.case") or "Nuevo"
        return super().create(vals_list)

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

    def action_validate(self):
        for case in self:
            if case.state != "received":
                raise UserError(_("Solo se puede validar un expediente con datos recibidos."))
            case.state = "validated"

    def action_send_gestoria(self):
        for case in self:
            if case.state != "validated":
                raise UserError(_("Solo se envía a la gestoría un expediente validado."))
            case.state = "sent"

    def action_cancel(self):
        for case in self:
            if case.state == "sent":
                raise UserError(_("Un expediente ya enviado no se puede cancelar."))
            case.state = "cancel"

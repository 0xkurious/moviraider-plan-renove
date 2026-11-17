import logging
import uuid

import requests

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

DEFAULT_URL = "http://mock-respondio:8000/webhook"
MAX_ATTEMPTS = 5
TIMEOUT = 5


class DgtWebhookEvent(models.Model):
    """Outbox: el evento se guarda en la misma transacción que el cambio de
    estado y un cron lo entrega después. Si respond.io cae, no se pierde nada."""

    _name = "dgt.webhook.event"
    _description = "Evento de webhook DGT (outbox)"
    _order = "id desc"

    event_id = fields.Char(string="ID de evento", default=lambda s: str(uuid.uuid4()), readonly=True, index=True)
    event_type = fields.Char(string="Evento", required=True)
    case_id = fields.Many2one("dgt.case", string="Expediente", ondelete="cascade", index=True)
    created_at = fields.Datetime(string="Creado", default=fields.Datetime.now, readonly=True)
    payload = fields.Json(string="Contenido")
    state = fields.Selection(
        [("pending", "Pendiente"), ("sent", "Enviado"), ("failed", "Fallido")],
        string="Estado",
        default="pending",
        index=True,
    )
    attempts = fields.Integer(string="Intentos", default=0)
    last_error = fields.Char(string="Último error")
    sent_date = fields.Datetime(string="Enviado el")

    @api.model
    def _target_url(self):
        return self.env["ir.config_parameter"].sudo().get_param(
            "moviraider_dgt.webhook_url", DEFAULT_URL
        )

    def _deliver(self):
        url = self._target_url()
        for event in self:
            body = dict(event.payload or {}, event_id=event.event_id)
            try:
                resp = requests.post(url, json=body, timeout=TIMEOUT)
                resp.raise_for_status()
            except requests.RequestException as exc:
                attempts = event.attempts + 1
                event.write(
                    {
                        "attempts": attempts,
                        "last_error": str(exc)[:250],
                        "state": "failed" if attempts >= MAX_ATTEMPTS else "pending",
                    }
                )
                _logger.warning("Webhook %s falló (%s/%s): %s", event.event_id, attempts, MAX_ATTEMPTS, exc)
            else:
                event.write(
                    {
                        "state": "sent",
                        "attempts": event.attempts + 1,
                        "last_error": False,
                        "sent_date": fields.Datetime.now(),
                    }
                )

    @api.model
    def _cron_dispatch(self, limit=50):
        self.search([("state", "=", "pending")], limit=limit, order="id")._deliver()

    def action_retry(self):
        self.filtered(lambda e: e.state == "failed").write({"state": "pending", "attempts": 0})
        self._deliver()

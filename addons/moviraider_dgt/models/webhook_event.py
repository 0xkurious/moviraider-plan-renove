import logging
import threading
import uuid

import requests

import odoo
from odoo import SUPERUSER_ID, api, fields, models

_logger = logging.getLogger(__name__)

DEFAULT_URL = "http://bridge:8000/webhook"
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

    @api.model_create_multi
    def create(self, vals_list):
        events = super().create(vals_list)
        # Entrega inmediata en cuanto el cambio de estado queda confirmado en la base de datos.
        # El cron sigue ahí como red de seguridad: lo que no salga ahora, sale en el siguiente minuto.
        dbname, ids = self.env.cr.dbname, events.ids
        self.env.cr.postcommit.add(lambda: self._spawn_delivery(dbname, ids))
        return events

    @api.model
    def _spawn_delivery(self, dbname, ids):
        def run():
            try:
                with odoo.registry(dbname).cursor() as cr:
                    env = api.Environment(cr, SUPERUSER_ID, {})
                    env["dgt.webhook.event"].browse(ids)._deliver_pending()
            except Exception:  # noqa: BLE001 - nunca debe romper la petición que originó el evento
                _logger.exception("Entrega inmediata fallida; el cron la reintentará")

        threading.Thread(target=run, name="dgt-webhook-delivery", daemon=True).start()

    def _deliver_pending(self):
        """Entrega solo lo que sigue pendiente y que nadie más esté entregando ya.

        FOR UPDATE SKIP LOCKED evita el doble envío cuando la entrega inmediata y el cron
        coinciden sobre el mismo evento (en WhatsApp, un duplicado lo ve el cliente)."""
        if not self:
            return
        self.flush_model(["state"])  # el ORM difiere las escrituras: el SQL de abajo debe ver el estado real
        self.env.cr.execute(
            "SELECT id FROM dgt_webhook_event WHERE id IN %s AND state = 'pending' "
            "ORDER BY id FOR UPDATE SKIP LOCKED",
            (tuple(self.ids),),
        )
        self.browse([row[0] for row in self.env.cr.fetchall()])._deliver()

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
                detail = str(exc)
                response = getattr(exc, "response", None)
                if response is not None:  # el motivo real (p. ej. «token inválido») viene en el cuerpo
                    detail = "%s: %s" % (response.status_code, (response.text or "")[:180])
                event.write(
                    {
                        "attempts": attempts,
                        "last_error": detail[:250],
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
        self.search([("state", "=", "pending")], limit=limit, order="id")._deliver_pending()

    def action_retry(self):
        self.filtered(lambda e: e.state == "failed").write({"state": "pending", "attempts": 0})
        self._deliver_pending()

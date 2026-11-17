"""Lógica del adaptador: evento canónico de Odoo -> mensaje de WhatsApp -> proveedor.

Solo biblioteca estándar. Garantías:
  * idempotente: el mismo event_id nunca genera dos mensajes (Odoo entrega «al menos una vez»);
  * en modo real solo envía a números de una lista permitida (los datos de demo llevan
    teléfonos inventados que podrían ser de personas reales);
  * ni el token ni los teléfonos completos aparecen en logs ni respuestas.
"""
import json
import os
import re
import threading

# ---- Textos de WhatsApp (modo texto: válidos dentro de la ventana de 24 h) -----------------
COPY = {
    "case.created": (
        "Hola {name} 👋 Tu pedido {order} incluye el pack legal. Para matricular tu {scooter} "
        "necesitamos 3 datos (DNI/NIE, nº de serie y tu autorización). Te lleva 2 minutos:\n{link}"
    ),
    "case.data_received": (
        "¡Gracias, {name}! Hemos recibido los datos de tu {scooter}. "
        "Nos ocupamos del resto del trámite y te avisamos."
    ),
    "case.sent_to_gestoria": (
        "Buenas noticias, {name}: tu expediente {reference} ya está en manos de la gestoría. "
        "En cuanto tengamos novedades te escribimos."
    ),
}

# ---- Plantillas (modo plantilla: lo único permitido fuera de la ventana de 24 h) ------------
# Hay que crearlas y aprobarlas en respond.io con EXACTAMENTE este cuerpo (docs/respondio-setup.md).
TEMPLATES = {
    "case.created": {
        "env": "TEMPLATE_CREATED", "default": "matricula_datos",
        "body": "Hola {{1}}, tu pedido {{2}} incluye el pack legal. Para matricular tu {{3}} necesitamos "
                "3 datos. Complétalos aquí (2 minutos): {{4}}",
        "params": ["name", "order", "scooter", "link"],
    },
    "case.data_received": {
        "env": "TEMPLATE_RECEIVED", "default": "matricula_recibida",
        "body": "Gracias {{1}}, hemos recibido los datos de tu {{2}}. Nos ocupamos del resto del trámite.",
        "params": ["name", "scooter"],
    },
    "case.sent_to_gestoria": {
        "env": "TEMPLATE_SENT", "default": "matricula_enviada",
        "body": "Hola {{1}}, tu expediente {{2}} ya está en manos de la gestoría. Te escribimos con novedades.",
        "params": ["name", "reference"],
    },
}


class ConfigError(Exception):
    pass


class ProviderError(Exception):
    """Fallo de red o del proveedor: Odoo debe reintentar."""


def normalize_phone(raw, default_cc="34"):
    """Teléfono -> E.164 (+34600111222) o None. Un móvil español de 9 dígitos recibe el +34."""
    if not raw:
        return None
    digits = re.sub(r"[^\d+]", "", str(raw))
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    if digits.startswith("+"):
        number = digits
    elif len(digits) == 9 and digits[0] in "679":
        number = "+" + default_cc + digits
    else:
        number = "+" + digits
    return number if re.fullmatch(r"\+\d{8,15}", number) else None


def mask(number):
    return number[:3] + "•" * max(len(number) - 5, 0) + number[-2:] if number else "—"


def _fields(payload):
    case, contact = payload.get("case", {}), payload.get("contact", {})
    name = (contact.get("name") or "").strip().split(" ")[0] or "cliente"
    return {
        "name": name,
        "order": case.get("order") or "",
        "scooter": case.get("scooter") or "patinete",
        "link": case.get("portal_url") or "",
        "reference": case.get("reference") or "",
    }


def render(event, payload, mode="text"):
    """Devuelve el mensaje en el formato de respond.io, o None si ese evento no se notifica."""
    if event not in COPY:
        return None
    values = _fields(payload)
    if mode == "template":
        tpl = TEMPLATES[event]
        return {
            "type": "whatsapp_template",
            "template": {
                "name": os.environ.get(tpl["env"], tpl["default"]),
                "languageCode": os.environ.get("TEMPLATE_LANGUAGE", "es"),
                "components": [{
                    "type": "body",
                    "text": tpl["body"],
                    "parameters": [{"type": "text", "text": values[k]} for k in tpl["params"]],
                }],
            },
        }
    return {"type": "text", "text": COPY[event].format(**values)}


class State:
    """event_ids ya procesados, persistidos para sobrevivir a reinicios."""

    def __init__(self, path=None):
        self.path, self.lock, self.seen = path, threading.Lock(), set()
        if path and os.path.exists(path):
            try:
                with open(path) as fh:
                    self.seen = set(json.load(fh))
            except (OSError, ValueError):
                self.seen = set()

    def has(self, event_id):
        with self.lock:
            return event_id in self.seen

    def add(self, event_id):
        with self.lock:
            self.seen.add(event_id)
            if self.path:
                try:
                    with open(self.path, "w") as fh:
                        json.dump(sorted(self.seen)[-5000:], fh)
                except OSError:
                    pass


class Bridge:
    def __init__(self, provider="mock", client=None, allowed=(), mode="text", state=None, fail_first_n=0):
        self.provider, self.client, self.mode = provider, client, mode
        self.allowed = {normalize_phone(p) for p in allowed if normalize_phone(p)}
        self.state = state or State()
        self.fail_first_n, self.posts = fail_first_n, 0
        self.events, self.messages = {}, []
        if provider == "respondio":
            if client is None:
                raise ConfigError("PROVIDER=respondio requiere RESPONDIO_TOKEN.")
            if not self.allowed:
                raise ConfigError(
                    "PROVIDER=respondio requiere LIVE_ALLOWED_PHONES (lista de números a los que se "
                    "permite escribir). Se niega a arrancar sin ella para no enviar a números inventados."
                )

    def _log(self, text, status):
        self.messages.append({"status": status, **text})
        del self.messages[:-200]

    def handle(self, payload):
        """-> (código HTTP, cuerpo JSON). Cualquier no-2xx hace que Odoo reintente."""
        self.posts += 1
        if self.posts <= self.fail_first_n:
            return 503, {"error": "fallo simulado"}
        event_id, event = payload.get("event_id"), payload.get("event")
        if not event_id or not event:
            return 400, {"error": "falta event_id o event"}
        if self.state.has(event_id):
            return 200, {"ok": True, "duplicate": True}
        self.events.setdefault(event_id, payload)

        message = render(event, payload, self.mode)
        if message is None:
            self.state.add(event_id)
            return 200, {"ok": True, "skipped": "este evento no genera mensaje"}

        phone = normalize_phone((payload.get("contact") or {}).get("phone"))
        meta = {"event": event, "event_id": event_id, "to": mask(phone), "message": message}
        if not phone:
            self.state.add(event_id)  # sin teléfono no se arregla reintentando
            self._log(meta, "sin_telefono")
            return 200, {"ok": True, "skipped": "sin teléfono válido"}

        if self.provider == "mock":
            self.state.add(event_id)
            self._log(meta, "simulado")
            return 200, {"ok": True, "sent": "mock"}

        if phone not in self.allowed:
            self.state.add(event_id)
            self._log(meta, "bloqueado_lista")
            return 200, {"ok": True, "skipped": "número fuera de LIVE_ALLOWED_PHONES"}

        try:
            status, detail = self.client.send(phone, message)
        except ProviderError as exc:
            self._log(meta, "error_red")
            return 503, {"error": "respond.io no responde: %s" % exc}
        if 200 <= status < 300:
            self.state.add(event_id)
            self._log(meta, "enviado")
            return 200, {"ok": True, "sent": "respondio"}
        self._log(meta, "error_%s" % status)
        # 429 y 5xx son transitorios; el resto (token, contacto inexistente, plantilla) hay que
        # arreglarlo a mano. En ambos casos Odoo reintenta y el motivo queda visible en su cola.
        code = 503 if status == 429 or status >= 500 else 502
        return code, {"error": "respond.io %s" % status, "detail": detail}

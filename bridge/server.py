"""Adaptador HTTP entre Odoo y el proveedor de mensajería.

POST /webhook   recibe el evento de Odoo (la «cola de webhooks» apunta aquí)
GET  /events    eventos recibidos (compatibilidad con el simulador anterior)
GET  /messages  mensajes generados, con el teléfono enmascarado
GET  /health    configuración activa, sin secretos

Variables (ver .env.example): PROVIDER=mock|respondio, RESPONDIO_TOKEN, RESPONDIO_CHANNEL_ID,
LIVE_ALLOWED_PHONES, MESSAGE_MODE=text|template, FAIL_FIRST_N.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from core import Bridge, ConfigError, State
from respondio import DEFAULT_BASE, RespondIO


def build_bridge(env=os.environ):
    provider = env.get("PROVIDER", "mock").strip().lower()
    client = None
    if provider == "respondio" and env.get("RESPONDIO_TOKEN", "").strip():
        client = RespondIO(
            env["RESPONDIO_TOKEN"].strip(),
            base_url=env.get("RESPONDIO_BASE_URL", DEFAULT_BASE),
            channel_id=env.get("RESPONDIO_CHANNEL_ID"),
        )
    allowed = [p for p in env.get("LIVE_ALLOWED_PHONES", "").split(",") if p.strip()]
    return Bridge(
        provider=provider, client=client, allowed=allowed,
        mode=env.get("MESSAGE_MODE", "text").strip().lower(),
        state=State(env.get("STATE_FILE", "/data/state.json")),
        fail_first_n=int(env.get("FAIL_FIRST_N", "0") or 0),
    )


def make_handler(bridge):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body):
            data = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/events":
                return self._send(200, list(bridge.events.values()))
            if self.path == "/messages":
                return self._send(200, bridge.messages)
            if self.path == "/health":
                return self._send(200, {"provider": bridge.provider, "mode": bridge.mode,
                                        "live_allowed_phones": len(bridge.allowed)})
            self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/webhook":
                return self._send(404, {"error": "not found"})
            try:
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            except ValueError:
                return self._send(400, {"error": "json inválido"})
            code, body = bridge.handle(payload)
            who = (bridge.messages[-1]["to"] if bridge.messages else "—")
            print("[bridge] %s %s -> %s (%s)" % (payload.get("event"), who, code, body.get("sent") or body.get("skipped")
                                                or body.get("error") or "ok"), flush=True)
            self._send(code, body)

        def log_message(self, *args):
            pass

    return Handler


if __name__ == "__main__":
    try:
        bridge = build_bridge()
    except ConfigError as exc:
        print("[bridge] CONFIGURACIÓN INVÁLIDA: %s" % exc, file=sys.stderr, flush=True)
        sys.exit(2)
    print("[bridge] listo en :8000 · provider=%s · mode=%s · números permitidos=%d" % (
        bridge.provider, bridge.mode, len(bridge.allowed)), flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8000), make_handler(bridge)).serve_forever()

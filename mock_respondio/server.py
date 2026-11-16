"""Receptor falso de webhooks (sustituye a respond.io en la demo).

POST /webhook  -> guarda el evento (dedupe por event_id) y lo imprime
GET  /events   -> lista lo recibido
Variable FAIL_FIRST_N=3 hace que los primeros N POST devuelvan 503,
para demostrar los reintentos del outbox.
"""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

EVENTS: dict[str, dict] = {}
STATE = {"posts": 0}
FAIL_FIRST_N = int(os.environ.get("FAIL_FIRST_N", "0"))


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body):
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/events":
            return self._send(200, list(EVENTS.values()))
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/webhook":
            return self._send(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._send(400, {"error": "invalid json"})
        STATE["posts"] += 1
        if STATE["posts"] <= FAIL_FIRST_N:
            print(f"[mock] simulated 503 (post #{STATE['posts']})", flush=True)
            return self._send(503, {"error": "simulated failure"})
        event_id = payload.get("event_id")
        duplicate = event_id in EVENTS
        EVENTS.setdefault(event_id, payload)
        print(f"[mock] {'DUP ' if duplicate else ''}{payload.get('event')} "
              f"{payload.get('case', {}).get('reference')} -> {payload.get('contact', {}).get('name')}",
              flush=True)
        self._send(200, {"ok": True, "duplicate": duplicate})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print(f"[mock] respond.io listening on :8000 (FAIL_FIRST_N={FAIL_FIRST_N})", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()

import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import Bridge, ConfigError, State, mask, normalize_phone, render  # noqa: E402
from respondio import RespondIO  # noqa: E402
from server import build_bridge  # noqa: E402

TOKEN = "tok_SECRETO_123"
ME = "+34600111222"


def payload(event="case.created", event_id="evt-1", phone="+34 600 111 222", name="María Pérez"):
    return {
        "event": event, "event_id": event_id,
        "case": {"reference": "DGT/2026/00007", "order": "S00472", "state": "pending",
                 "scooter": "Ecoxtrem M41", "portal_url": "http://192.168.0.26:8069/my/dgt/7?access_token=abc"},
        "contact": {"name": name, "email": "m@example.com", "phone": phone},
    }


class FakeRespondIO:
    """Servidor que hace de api.respond.io y apunta lo que recibe."""

    def __init__(self, status=200, reply="{}"):
        self.requests, self.status, self.reply = [], status, reply
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
                data = outer.reply.encode()
                self.send_response(outer.status)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d/v2" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class TestPhone(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_phone("+34 600 111 222"), ME)
        self.assertEqual(normalize_phone("600111222"), ME)             # móvil español sin prefijo
        self.assertEqual(normalize_phone("0034600111222"), ME)
        self.assertEqual(normalize_phone("+1 (555) 010-9999"), "+15550109999")
        self.assertIsNone(normalize_phone("abc"))
        self.assertIsNone(normalize_phone(""))
        self.assertIsNone(normalize_phone(None))

    def test_mask_hides_the_middle(self):
        self.assertEqual(mask(ME), "+34•••••••22")
        self.assertNotIn("600111", mask(ME))


class TestRender(unittest.TestCase):
    def test_text_uses_first_name_and_link(self):
        msg = render("case.created", payload(), "text")
        self.assertEqual(msg["type"], "text")
        self.assertIn("Hola María", msg["text"])
        self.assertNotIn("Pérez", msg["text"])
        self.assertIn("S00472", msg["text"])
        self.assertIn("http://192.168.0.26:8069/my/dgt/7?access_token=abc", msg["text"])

    def test_every_notified_event_renders_and_others_do_not(self):
        for ev in ("case.created", "case.data_received", "case.sent_to_gestoria"):
            self.assertTrue(render(ev, payload(ev))["text"], ev)
        self.assertIsNone(render("case.validated", payload()))
        self.assertIsNone(render("case.cancelled", payload()))

    def test_template_mode_matches_respondio_shape(self):
        msg = render("case.created", payload(), "template")
        self.assertEqual(msg["type"], "whatsapp_template")
        tpl = msg["template"]
        self.assertEqual(tpl["name"], "matricula_datos")
        self.assertEqual(tpl["languageCode"], "es")
        body = tpl["components"][0]
        self.assertEqual(body["type"], "body")
        self.assertEqual([p["text"] for p in body["parameters"]],
                         ["María", "S00472", "Ecoxtrem M41", "http://192.168.0.26:8069/my/dgt/7?access_token=abc"])
        self.assertEqual(body["text"].count("{{"), len(body["parameters"]))  # variables y parámetros cuadran

    def test_missing_name_and_scooter_have_safe_defaults(self):
        p = payload(name="")
        p["case"]["scooter"] = None
        self.assertIn("Hola cliente", render("case.created", p)["text"])
        self.assertIn("tu patinete", render("case.created", p)["text"])


class TestMockProvider(unittest.TestCase):
    def test_records_message_without_network_and_masks_phone(self):
        b = Bridge("mock")
        code, body = b.handle(payload())
        self.assertEqual((code, body["sent"]), (200, "mock"))
        self.assertEqual(b.messages[0]["to"], "+34•••••••22")
        self.assertNotIn("600111222", json.dumps(b.messages))

    def test_duplicate_event_id_is_idempotent(self):
        b = Bridge("mock")
        b.handle(payload())
        code, body = b.handle(payload())
        self.assertTrue(body["duplicate"])
        self.assertEqual(len(b.messages), 1)

    def test_events_without_message_are_acknowledged_not_retried(self):
        b = Bridge("mock")
        code, body = b.handle(payload("case.validated"))
        self.assertEqual(code, 200)
        self.assertIn("skipped", body)

    def test_no_phone_is_skipped_not_retried(self):
        b = Bridge("mock")
        code, body = b.handle(payload(phone=None))
        self.assertEqual(code, 200)
        self.assertEqual(b.messages[0]["status"], "sin_telefono")

    def test_bad_payload_is_400(self):
        self.assertEqual(Bridge("mock").handle({"event": "case.created"})[0], 400)

    def test_fail_first_n_simulates_outage_then_recovers(self):
        b = Bridge("mock", fail_first_n=2)
        self.assertEqual(b.handle(payload())[0], 503)
        self.assertEqual(b.handle(payload())[0], 503)
        self.assertEqual(b.handle(payload())[0], 200)

    def test_state_survives_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "state.json")
            Bridge("mock", state=State(path)).handle(payload())
            again = Bridge("mock", state=State(path))
            self.assertTrue(again.handle(payload())[1]["duplicate"])


class TestRespondIO(unittest.TestCase):
    def setUp(self):
        self.api = FakeRespondIO()
        self.addCleanup(self.api.close)

    def bridge(self, **kw):
        client = RespondIO(TOKEN, base_url=self.api.url, channel_id=kw.pop("channel_id", None))
        return Bridge("respondio", client=client, allowed=kw.pop("allowed", [ME]), **kw)

    def test_sends_text_to_the_right_endpoint_with_bearer_token(self):
        code, body = self.bridge().handle(payload())
        self.assertEqual((code, body["sent"]), (200, "respondio"))
        req = self.api.requests[0]
        self.assertEqual(req["path"], "/v2/contact/phone:+34600111222/message")
        self.assertEqual(req["auth"], "Bearer " + TOKEN)
        self.assertEqual(req["body"]["message"]["type"], "text")
        self.assertIn("Hola María", req["body"]["message"]["text"])
        self.assertNotIn("channelId", req["body"])      # sin canal: usa el último con el que habló el contacto

    def test_channel_id_is_sent_when_configured(self):
        self.bridge(channel_id="5678").handle(payload())
        self.assertEqual(self.api.requests[0]["body"]["channelId"], 5678)

    def test_template_mode_sends_whatsapp_template(self):
        self.bridge(mode="template", channel_id="5678").handle(payload())
        msg = self.api.requests[0]["body"]["message"]
        self.assertEqual(msg["type"], "whatsapp_template")
        self.assertEqual(msg["template"]["name"], "matricula_datos")

    def test_number_outside_allowlist_is_never_contacted(self):
        b = self.bridge()
        code, body = b.handle(payload(phone="+34 699 000 000", event_id="evt-x"))
        self.assertEqual(code, 200)
        self.assertIn("LIVE_ALLOWED_PHONES", body["skipped"])
        self.assertEqual(self.api.requests, [])          # ni una sola petición a respond.io
        self.assertEqual(b.messages[0]["status"], "bloqueado_lista")

    def test_allowlist_accepts_any_phone_format(self):
        b = self.bridge(allowed=["600 111 222"])
        self.assertEqual(b.handle(payload())[1]["sent"], "respondio")

    def test_refuses_to_start_without_allowlist_or_token(self):
        with self.assertRaises(ConfigError):
            Bridge("respondio", client=RespondIO(TOKEN), allowed=[])
        with self.assertRaises(ConfigError):
            Bridge("respondio", client=None, allowed=[ME])

    def test_duplicate_is_sent_once(self):
        b = self.bridge()
        b.handle(payload())
        b.handle(payload())
        self.assertEqual(len(self.api.requests), 1)

    def test_auth_error_is_502_with_reason_and_is_retryable(self):
        self.api.status, self.api.reply = 401, '{"message":"Invalid token"}'
        b = self.bridge()
        code, body = b.handle(payload())
        self.assertEqual(code, 502)
        self.assertIn("Invalid token", body["detail"])
        self.api.status, self.api.reply = 200, "{}"
        self.assertEqual(b.handle(payload())[0], 200)     # no se marcó como entregado: el reintento funciona

    def test_rate_limit_and_server_errors_are_503(self):
        for status in (429, 500, 503):
            self.api.status = status
            self.assertEqual(self.bridge().handle(payload(event_id="e%s" % status))[0], 503, status)

    def test_network_down_is_503(self):
        client = RespondIO(TOKEN, base_url="http://127.0.0.1:1/v2", timeout=1)
        b = Bridge("respondio", client=client, allowed=[ME])
        self.assertEqual(b.handle(payload())[0], 503)

    def test_token_never_appears_in_responses_or_message_log(self):
        self.api.status, self.api.reply = 401, "nope"
        b = self.bridge()
        out = json.dumps(b.handle(payload())) + json.dumps(b.messages)
        self.assertNotIn(TOKEN, out)


class TestBuild(unittest.TestCase):
    def test_default_is_mock(self):
        self.assertEqual(build_bridge({"STATE_FILE": ""}).provider, "mock")

    def test_live_without_allowlist_is_rejected(self):
        with self.assertRaises(ConfigError):
            build_bridge({"PROVIDER": "respondio", "RESPONDIO_TOKEN": TOKEN, "STATE_FILE": ""})

    def test_live_without_token_is_rejected(self):
        with self.assertRaises(ConfigError):
            build_bridge({"PROVIDER": "respondio", "LIVE_ALLOWED_PHONES": ME, "STATE_FILE": ""})

    def test_live_builds_with_token_and_allowlist(self):
        b = build_bridge({"PROVIDER": "respondio", "RESPONDIO_TOKEN": TOKEN,
                          "LIVE_ALLOWED_PHONES": "+34 600 111 222, 699000000", "STATE_FILE": ""})
        self.assertEqual(b.allowed, {ME, "+34699000000"})


if __name__ == "__main__":
    unittest.main()

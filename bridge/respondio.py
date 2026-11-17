"""Cliente mínimo de la API de respond.io (v2): POST /contact/{identifier}/message."""
import json
import urllib.error
import urllib.request
from urllib.parse import quote

from core import ProviderError

DEFAULT_BASE = "https://api.respond.io/v2"


class RespondIO:
    def __init__(self, token, base_url=DEFAULT_BASE, channel_id=None, timeout=8):
        self.token, self.base_url, self.timeout = token, base_url.rstrip("/"), timeout
        self.channel_id = int(channel_id) if str(channel_id or "").isdigit() else None

    def send(self, phone_e164, message):
        """-> (status HTTP, cuerpo recortado). Lanza ProviderError si no hay red."""
        body = {"message": message}
        if self.channel_id is not None:   # sin channelId usa el último canal con el que habló el contacto
            body["channelId"] = self.channel_id
        url = "%s/contact/%s/message" % (self.base_url, quote("phone:" + phone_e164, safe=":+"))
        request = urllib.request.Request(
            url, data=json.dumps(body).encode(), method="POST",
            headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                return resp.status, resp.read().decode("utf-8", "replace")[:500]
        except urllib.error.HTTPError as err:
            try:
                return err.code, err.read().decode("utf-8", "replace")[:500]
            finally:
                err.close()  # sin esto cada error HTTP deja una conexión abierta
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            raise ProviderError(str(getattr(err, "reason", err))) from err

#!/usr/bin/env bash
# Fija la URL pública de Odoo a la IP de tu Wi-Fi para que el enlace del mensaje se abra desde el móvil.
# Uso: ./scripts/lan_url.sh            (detecta la IP)   |   ./scripts/lan_url.sh 192.168.0.26
set -euo pipefail
cd "$(dirname "$0")/.."
IP="${1:-$(ip -4 route get 1.1.1.1 | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -1)}"
[ -n "$IP" ] || { echo "No pude detectar la IP. Pásala como argumento."; exit 1; }
URL="http://$IP:8069"
docker compose exec -T db psql -U odoo -d moviraider -qc "
  INSERT INTO ir_config_parameter(key, value, create_uid, write_uid, create_date, write_date)
  VALUES ('web.base.url', '$URL', 1, 1, now(), now()), ('web.base.url.freeze', 'True', 1, 1, now(), now())
  ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, write_date = now();"
docker compose restart odoo >/dev/null
echo "✓ Odoo usará $URL en los enlaces de los mensajes."
echo "  Prueba desde el móvil (misma Wi-Fi):  $URL/renove"
echo "  Si no abre, es el cortafuegos del ordenador: permite el puerto 8069 en tu red local."

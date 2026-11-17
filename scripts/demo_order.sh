#!/usr/bin/env bash
# Lanza la demo en directo: crea un pedido con pack legal para TU número y dispara el WhatsApp.
# Uso: ./scripts/demo_order.sh +34600111222 "Tu nombre"   (el número solo se guarda en la base de datos local)
set -euo pipefail
cd "$(dirname "$0")/.."
PHONE="${1:-}"
NAME="${2:-Cliente Demo}"
[ -n "$PHONE" ] || { echo "Uso: $0 +34XXXXXXXXX \"Tu nombre\""; exit 1; }
docker compose exec -T -e DEMO_PHONE="$PHONE" -e DEMO_NAME="$NAME" odoo odoo shell -d moviraider --no-http < scripts/demo_order.py 2>&1 | grep -E "DEMO_OK|Error|Traceback" || true
echo "→ Mira tu WhatsApp. Estado del adaptador:  curl -s localhost:8001/messages"

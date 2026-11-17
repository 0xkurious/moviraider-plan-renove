#!/usr/bin/env bash
# Reconstruye la demo desde cero: base vacía -> módulos -> datos sintéticos.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "› Parando Odoo y recreando la base 'moviraider'…"
docker compose stop odoo >/dev/null
docker compose up -d db mock-respondio >/dev/null
until docker compose exec -T db pg_isready -U odoo >/dev/null 2>&1; do sleep 1; done
docker compose exec -T db psql -U odoo -d postgres -qc "DROP DATABASE IF EXISTS moviraider"

echo "› Instalando módulos (puede tardar ~1 min)…"
docker compose run --rm -T odoo odoo -d moviraider \
  -i website_sale,moviraider_catalog,moviraider_dgt,moviraider_renove \
  --load-language=es_ES --without-demo=all --stop-after-init 2>&1 | grep -E "ERROR|CRITICAL" || true

echo "› Arrancando Odoo y cargando datos sintéticos…"
docker compose up -d odoo >/dev/null
sleep 8
cat scripts/seed.py scripts/branding.py scripts/product_images.py | docker compose exec -T odoo odoo shell -d moviraider --no-http 2>&1 | grep -vE "INFO|WARNING|^$"

# Odoo cachea las plantillas web: reiniciar para que sirva lo que acaba de escribir el seed.
docker compose restart odoo >/dev/null

echo "✓ Listo: http://localhost:8069  (usuario: admin / contraseña: admin)"

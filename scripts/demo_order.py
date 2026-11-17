# Crea un pedido nuevo con pack legal para el cliente de la demo en directo.
# Lo lanza scripts/demo_order.sh con el teléfono en la variable DEMO_PHONE (no se guarda en git).
import os

phone = os.environ.get("DEMO_PHONE", "").strip()  # noqa: F821
name = os.environ.get("DEMO_NAME", "").strip() or "Cliente Demo"  # noqa: F821
assert phone, "Falta DEMO_PHONE"
scooter = env["product.product"].search([("is_scooter", "=", True), ("has_dgt_certificate", "=", True)], limit=1)  # noqa: F821
pack = env["product.product"].search([("is_legal_pack", "=", True)], limit=1)  # noqa: F821
partner = env["res.partner"].search([("name", "=", name)], limit=1)  # noqa: F821
if not partner:
    partner = env["res.partner"].create({"name": name, "email": "demo@moviraider-demo.example"})  # noqa: F821
partner.mobile = phone
order = env["sale.order"].create({  # noqa: F821
    "partner_id": partner.id,
    "order_line": [(0, 0, {"product_id": p.id, "product_uom_qty": 1}) for p in (scooter, pack)],
})
order.action_confirm()
env.cr.commit()  # noqa: F821
# Este script vive en un shell de Odoo que termina enseguida y mataría el hilo de entrega inmediata
# (en el servidor web sí funciona). Se entrega aquí, de forma síncrona, para no esperar al cron.
env["dgt.webhook.event"]._cron_dispatch()  # noqa: F821
env.cr.commit()  # noqa: F821
case = order.dgt_case_ids
print("DEMO_OK pedido=%s expediente=%s enlace=%s" % (order.name, case.name, case.portal_url))

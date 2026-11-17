"""Datos sintéticos deterministas para la demo.  Uso (lo hace scripts/reset.sh):

    odoo shell -d moviraider --no-http < scripts/seed.py

Todo es inventado: nombres, emails (@example.com), teléfonos y volúmenes.
Los modelos reutilizan marcas del catálogo público; los precios de los modelos
vigentes salen de la web, el resto son plausibles pero inventados.
"""
import random
from datetime import datetime, timedelta

rnd = random.Random(42)
NOW = datetime(2026, 11, 16, 12, 0)
CUTOFF = datetime(2024, 1, 22)

env.user.lang = "es_ES"  # noqa: F821

# ---- Marca y moneda de la demo (la empresa por defecto de Odoo es "My Company" en USD)
eur = env.ref("base.EUR")  # noqa: F821
eur.active = True
env.company.write({"name": "MoviRaider (demo)", "currency_id": eur.id})  # noqa: F821
env["product.pricelist"].search([]).write({"currency_id": eur.id})  # noqa: F821
env["website"].search([]).write({"name": "MoviRaider (demo)"})  # noqa: F821
P = env["product.product"]  # noqa: F821
Partner = env["res.partner"]  # noqa: F821
SO = env["sale.order"]  # noqa: F821

# ------------------------------------------------------------------ catálogo
# (nombre, precio, peso kg, vel. km/h, certificado)
LEGACY = [
    ("Kukirin G2 Pro (2022)", 749, 30.5, 45, False),
    ("Ecoxtrem M41 (2022)", 599, 24.0, 40, False),
    ("Joyor S5 (2021)", 489, 19.5, 35, False),
    ("Smartgyro K2 Pro (2022)", 429, 17.0, 30, False),
    ("Dualtron Mini (2022)", 899, 23.0, 50, False),
    ("ZWheel ZRino (2023)", 579, 22.0, 35, False),
    ("Joyor X5S (2023, con certificado)", 649, 21.5, 25, True),  # caso límite
]
CURRENT = [
    ("Ecoxtrem M41 Armored Dual PRO", 847, 41.0, 25, True),
    ("Xtreme F1 DGT", 527, 23.0, 25, True),
    ("Xtreme F1 MAX DGT", 747, 31.0, 25, True),
    ("Joyor T6D", 629, 25.0, 25, True),
    ("UrbanGlide Ride 100 EVO", 287, 14.0, 25, True),
    ("Segway Ninebot Max G3 E", 799, 20.0, 25, True),
]


def scooter(name, price, weight, speed, cert):
    return P.create({
        "name": name, "list_price": price, "type": "consu", "is_scooter": True,
        "has_dgt_certificate": cert, "weight_kg": weight, "max_speed_kmh": speed,
    })


legacy = [scooter(*r) for r in LEGACY]
current = [scooter(*r) for r in CURRENT]
pack = P.create({"name": "Pack legal · Registro DGT y matrícula", "list_price": 57,
                 "type": "service", "is_legal_pack": True})
helmet = P.create({"name": "Pack Base - Casco y chaleco reflectante", "list_price": 29.99, "type": "consu"})
lock = P.create({"name": "Candado antirrobo", "list_price": 19.9, "type": "consu"})

# ------------------------------------------------------------------ clientes
FIRST = ["Lucía", "Pablo", "Marta", "Raúl", "Carmen", "Javier", "Elena", "Sergio", "Irene", "Álvaro",
         "Paula", "Diego", "Sara", "Adrián", "Laura", "Iván", "Noelia", "Rubén", "Cristina", "Manuel"]
LAST = ["García", "Martínez", "López", "Sánchez", "Pérez", "Gómez", "Ruiz", "Hernández", "Díaz", "Moreno",
        "Muñoz", "Álvarez", "Romero", "Navarro", "Torres", "Domínguez", "Gil", "Vázquez", "Serrano", "Ramos"]
CITIES = ["Sevilla", "Sevilla", "Sevilla", "València", "Toledo", "Arrecife"]


def partner(name, email=True, consent=True, idx=0):
    return Partner.create({
        "name": name,
        "email": ("%s.%03d@example.com" % (name.split()[0].lower().replace("á", "a").replace("ú", "u")
                                           .replace("í", "i").replace("é", "e"), idx)) if email else False,
        "mobile": ("+34 6%02d %03d %03d" % (rnd.randint(0, 99), rnd.randint(0, 999), rnd.randint(0, 999))) if email else False,
        "city": rnd.choice(CITIES),
        "marketing_consent": consent,
    })


customers = []
for i in range(420):
    in_store = rnd.random() < 0.35          # compra en tienda: sin datos de contacto
    consent = (not in_store) and rnd.random() < 0.65
    customers.append(partner("%s %s" % (rnd.choice(FIRST), rnd.choice(LAST)), email=not in_store,
                             consent=consent, idx=i))


def sale(cust, products, when):
    so = SO.create({"partner_id": cust.id,
                    "order_line": [(0, 0, {"product_id": p.id, "product_uom_qty": 1}) for p in products]})
    so.action_confirm()
    so.date_order = when  # action_confirm lo pisa con "ahora"
    return so


def rand_date(a, b):
    return a + timedelta(seconds=rnd.randint(0, int((b - a).total_seconds())))


# ---------------------------------------------------------- casos límite con nombre
edge = {
    "dos": partner("Lucía Ortega (caso: 2 patinetes antiguos)", idx=901),
    "renovado": partner("Pablo Rivas (caso: ya renovó)", idx=902),
    "sin_email": partner("Marta Gil (caso: sin email)", email=False, idx=903),
    "sin_consent": partner("Raúl Cano (caso: sin consentimiento)", consent=False, idx=904),
}
sale(edge["dos"], [legacy[0]], datetime(2022, 6, 3))
sale(edge["dos"], [legacy[2]], datetime(2023, 3, 18))
sale(edge["renovado"], [legacy[1]], datetime(2022, 11, 9))
sale(edge["renovado"], [current[1]], datetime(2025, 4, 14))
sale(edge["sin_email"], [legacy[3]], datetime(2023, 8, 2))
sale(edge["sin_consent"], [legacy[4]], datetime(2022, 12, 20))

# ------------------------------------------------------------------ histórico
# Norma: cada cliente compró UN patinete; solo ~6 % repite (como en una tienda de este tipo,
# donde el patinete es una compra poco frecuente).  Supuesto declarado en el README.
def historic_order(cust):
    when = rand_date(datetime(2022, 1, 10), datetime(2026, 9, 30))
    if when < CUTOFF:
        item = rnd.choice(legacy) if rnd.random() < 0.93 else legacy[6]
    else:
        item = rnd.choice(current)
    extras = [rnd.choice([helmet, lock])] if rnd.random() < 0.3 else []
    sale(cust, [item] + extras, when)


for cust in customers:
    historic_order(cust)
for cust in rnd.sample(customers, 25):
    historic_order(cust)

# ------------------------------------------------- pedidos actuales con pack legal
buyers = [c for c in customers if c.email]
rnd.shuffle(buyers)
plan = (["pending"] * 6 + ["stalled"] * 4 + ["received"] * 4 + ["validated"] * 3 + ["sent"] * 3)
SERIAL = "MR%s-%05d"
for n, kind in enumerate(plan):
    age = rnd.randint(6, 12) if kind == "stalled" else rnd.randint(0, 3) if kind == "pending" else rnd.randint(2, 9)
    when = NOW - timedelta(days=age)
    so = sale(buyers[n], [rnd.choice(current), pack], when)
    case = so.dgt_case_ids
    env.cr.execute("UPDATE dgt_case SET create_date=%s WHERE id=%s", (when, case.id))  # noqa: F821
    case.invalidate_recordset()
    if kind in ("received", "validated", "sent"):
        case.write({"owner_vat": "%08d%s" % (rnd.randint(10**7, 10**8 - 1), "TRWAGMYFPDXBNJZSQVHLCKE"[n % 23]),
                    "serial_number": SERIAL % (n, rnd.randint(0, 99999)), "consent_gestoria": True})
        case.action_submit_data()
    if kind in ("validated", "sent"):
        case.action_validate()
    if kind == "sent":
        case.action_send_gestoria()
        case.flush_recordset()
        # cierre realista: el expediente se enviaba 1-3 días después de abrirse
        closed = when + timedelta(days=rnd.randint(1, 3))
        env.cr.execute("UPDATE dgt_case SET write_date=%s WHERE id=%s", (closed, case.id))  # noqa: F821
        case.invalidate_recordset()

# ------------------------------------------------ tienda web: publicar lo vigente
(env["product.template"]  # noqa: F821
    .search([("is_scooter", "=", True), ("has_dgt_certificate", "=", True)])
    | pack.product_tmpl_id).write({"is_published": True, "website_published": True})

# ------------------------------------------------ web de la demo: menú y marca neutra
import base64  # noqa: E402

site = env["website"].search([], limit=1)  # noqa: F821
Menu = env["website.menu"]  # noqa: F821
top = site.menu_id
for m in top.child_id:
    if m.url == "/shop":
        m.name = "Patinetes"
dropdown = Menu.create({"name": "Matrícula y seguro", "url": "#", "parent_id": top.id,
                        "website_id": site.id, "sequence": 30})
Menu.create({"name": "¿Caduca tu patinete?", "url": "/renove", "parent_id": dropdown.id,
             "website_id": site.id, "sequence": 1})
Menu.create({"name": "Pack legal DGT", "url": pack.product_tmpl_id.website_url or "/shop",
             "parent_id": dropdown.id, "website_id": site.id, "sequence": 2})

# Marca neutra de demo: solo texto, no se usa ningún logo de la empresa real.
LOGO = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="64" viewBox="0 0 320 64">'
    '<text x="0" y="46" font-family="Helvetica, Arial, sans-serif" font-size="42" font-weight="800" '
    'fill="#111" letter-spacing="1">MOVI<tspan fill="#ff5a1f">RAIDER</tspan></text>'
    '<text x="232" y="60" font-family="Helvetica, Arial, sans-serif" font-size="11" fill="#888">demo</text></svg>'
)
site.logo = base64.b64encode(LOGO.encode())

# ------------------------------------------------------------------ campaña
campaign = env["renove.campaign"].create({"name": "Plan Renove 2027"})  # noqa: F821
campaign.action_compute_segment()
campaign.action_prepare_mailing()
env.cr.commit()  # noqa: F821

C = campaign
print("=== SEED OK ===")
print("clientes: %d | pedidos confirmados: %d | expedientes DGT: %d" % (
    Partner.search_count([("marketing_consent", "in", [True, False]), ("id", "in", [c.id for c in customers])]),
    SO.search_count([("state", "=", "sale")]), env["dgt.case"].search_count([])))  # noqa: F821
print("segmento Renove -> contactables: %d | sin consentimiento: %d | sin contacto: %d | ya renovados: %d" % (
    C.eligible_count, C.no_consent_count, C.no_contact_count, C.renewed_count))
print("días hasta el fin del periodo transitorio: %d" % C.days_left)

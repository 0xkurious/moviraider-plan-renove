# Retoca los textos de relleno de Odoo (pie de página, contacto) para que la demo se lea como una tienda.
# Se ejecuta tras seed.py:  cat scripts/seed.py scripts/branding.py | odoo shell ...
# Solo datos ficticios: dominio .example y teléfono de prueba, nunca datos reales de la empresa.
PHONE = "+34 900 000 000"
EMAIL = "hola@moviraider-demo.example"

env.company.write({"phone": PHONE, "email": EMAIL})  # noqa: F821
View = env["ir.views" if False else "ir.ui.view"]  # noqa: F821


def es_replace(key, pairs):
    for view in View.search([("key", "=", key)]):
        arch = view.with_context(lang="es_ES").arch_db
        for old, new in pairs:
            arch = arch.replace(old, new)
        view.with_context(lang="es_ES").write({"arch_db": arch})


es_replace("website.footer_custom", [
    ("Enlaces útiles", "Navegación"),
    ("Sobre nosotros</h5>", "Tu patinete, en buenas manos</h5>"),
    ("Somos un equipo de personas apasionadas cuyo objetivo es mejorar la vida de todos a través de productos "
     "disruptivos. Construimos grandes productos para resolver sus problemas de negocio.",
     "Venta de patinetes eléctricos homologados, taller multimarca y gestión de matrícula y seguro."),
    ("Nuestros productos están diseñados para pequeñas y medianas empresas dispuestas a optimizar su rendimiento.",
     "Sitio de demostración: los datos de contacto y los productos son ficticios."),
    ("info@sucompañía.example.com", EMAIL),
    ("info@yourcompany.example.com", EMAIL),
    ("+1 555-555-5556", PHONE),
])
es_replace("website.layout_footer_copyright", [("Nombre de la empresa", "MoviRaider (demo)"),
                                               ("Company name", "MoviRaider (demo)")])
# El teléfono son solo cifras: Odoo no traduce textos sin letras, así que hay que cambiar el ORIGINAL (en_US).
for view in View.search([("arch_db", "like", "555-555-5556")]):
    arch = view.with_context(lang="en_US").arch_db.replace("+1 555-555-5556", PHONE)
    view.with_context(lang="en_US").write({"arch_db": arch})

es_replace("website.footer_copyright_company_name", [("Nombre de la empresa", "MoviRaider (demo)"),
                                                     ("Company name", "MoviRaider (demo)")])

env.cr.commit()  # noqa: F821
print("branding OK")

# Imágenes de producto neutras para la demo (no se usa ninguna imagen de la empresa real).
# Fondo oscuro, franja naranja, marca/modelo y la insignia DGT.
import base64
import io

from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/lib/python3/dist-packages/reportlab/fonts/DejaVuSans-Bold.ttf"


def font(size):
    try:
        return ImageFont.truetype(FONT, size)
    except OSError:
        return ImageFont.load_default()


def make_image(title, subtitle="", badge=True):
    W = 800
    img = Image.new("RGB", (W, W), "#141414")
    d = ImageDraw.Draw(img)
    d.polygon([(0, W), (0, int(W * 0.58)), (int(W * 0.62), W)], fill="#ff5a1f")      # franja naranja
    d.polygon([(int(W * 0.7), W), (W, int(W * 0.62)), (W, W)], fill="#262626")
    brand, _, rest = title.partition(" ")
    d.text((56, 150), brand.upper(), font=font(92), fill="#ffffff")
    y = 270
    words = rest.split()
    line = ""
    for w in words:                                                                    # el modelo, en varias líneas
        if d.textlength(line + " " + w, font=font(46)) > W - 112 and line:
            d.text((56, y), line.strip(), font=font(46), fill="#d8d8d8"); y += 60; line = ""
        line += " " + w
    if line.strip():
        d.text((56, y), line.strip(), font=font(46), fill="#d8d8d8")
    if subtitle:
        d.text((56, W - 96), subtitle, font=font(30), fill="#ffffff")
    if badge:
        d.rounded_rectangle((W - 214, 40, W - 40, 102), radius=12, fill="#ff5a1f")
        d.text((W - 190, 52), "DGT", font=font(40), fill="#ffffff")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return base64.b64encode(buf.getvalue())


T = env["product.template"]  # noqa: F821
for tmpl in T.search([("is_scooter", "=", True)]):
    tmpl.image_1920 = make_image(tmpl.name, "%d km/h · %d kg" % (tmpl.max_speed_kmh, tmpl.weight_kg),
                                 badge=tmpl.has_dgt_certificate)
for tmpl in T.search([("is_legal_pack", "=", True)]):
    tmpl.image_1920 = make_image("Pack legal", "Registro DGT y matrícula", badge=False)
env.cr.commit()  # noqa: F821
print("imágenes OK")

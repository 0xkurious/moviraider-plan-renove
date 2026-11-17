import unicodedata
from datetime import date

from odoo import _, http
from odoo.http import request

from ..models.request import STORES

FALLBACK_DEADLINE = date(2027, 1, 22)


def _norm(text):
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower().strip()


class RenoveWeb(http.Controller):
    """Landing pública del Plan Renove: comprobador de caducidad y reserva de visita."""

    # --- helpers -------------------------------------------------------
    def _campaign(self):
        return request.env["renove.campaign"].sudo().get_active()

    def _scooters(self):
        return request.env["product.template"].sudo().search([("is_scooter", "=", True)], order="name")

    def _days_left(self, campaign):
        if campaign:
            return campaign.days_left
        return max((FALLBACK_DEADLINE - date.today()).days, 0)

    def _verdict(self, query):
        """('ok' | 'expires' | 'unknown', plantilla o None).

        Supuesto declarado: se decide por MODELO, no por unidad concreta."""
        q = _norm(query)
        if not q:
            return None, None
        scooters = self._scooters()
        match = scooters.filtered(lambda t: _norm(t.name) == q)
        if not match:
            partial = scooters.filtered(lambda t: q in _norm(t.name))
            match = partial if len(partial) == 1 else scooters.browse()
        if not match:
            return "unknown", None
        return ("ok" if match[:1].has_dgt_certificate else "expires"), match[:1]

    def _values(self, query=None, **extra):
        campaign = self._campaign()
        verdict, template = self._verdict(query)
        shop_url = "/shop"
        if campaign and campaign.utm_campaign_id:
            shop_url = "/shop?utm_campaign=%s&utm_source=web&utm_medium=landing" % (
                campaign.utm_campaign_id.name.replace(" ", "%20")
            )
        values = {
            "query": query or "",
            "verdict": verdict,
            "template": template,
            "scooters": self._scooters(),
            "days_left": self._days_left(campaign),
            "discount_code": campaign.discount_code if campaign else "",
            "discount_percent": campaign.discount_percent if campaign and campaign.loyalty_program_id else 0,
            "deadline_text": campaign.deadline.strftime("%d/%m/%Y") if campaign else FALLBACK_DEADLINE.strftime("%d/%m/%Y"),
            "shop_url": shop_url,
            "stores": STORES,
            "error": None,
            "sent": False,
            "form": {},
        }
        values.update(extra)
        return values

    # --- rutas ---------------------------------------------------------
    @http.route("/renove", type="http", auth="public", website=True, sitemap=True)
    def landing(self, model=None, store=None, **kw):
        values = self._values(model)
        if store in STORES:
            values["form"] = {"store": store}  # QR de tienda: llega con la tienda preseleccionada
        return request.render("moviraider_renove.landing", values)

    @http.route("/renove/reserva", type="http", auth="public", website=True, methods=["POST"], sitemap=False)
    def reserve(self, **post):
        name = (post.get("name") or "").strip()
        contact = (post.get("contact") or "").strip()
        model = (post.get("model") or "").strip()
        store = post.get("store")
        values = self._values(model, form=post)
        if not name or not contact:
            values["error"] = _("Necesitamos tu nombre y un teléfono o email para poder avisarte.")
        elif store not in STORES:
            values["error"] = _("Elige la tienda donde quieres que lo revisemos.")
        elif post.get("consent") != "on":
            values["error"] = _("Para contactarte necesitamos que aceptes que lo hagamos.")
        if values["error"]:
            return request.render("moviraider_renove.landing", values)

        campaign = self._campaign()
        request.env["renove.request"].sudo().create(
            {
                "name": name[:120],
                "contact": contact[:120],
                "model_text": model[:120],
                "product_tmpl_id": values["template"].id if values["template"] else False,
                "store": store,
                "campaign_id": campaign.id if campaign else False,
                "consent": True,
            }
        )
        values["sent"] = True
        values["form"] = {"store": store}
        return request.render("moviraider_renove.landing", values)

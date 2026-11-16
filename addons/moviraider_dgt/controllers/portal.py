from odoo import _, http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request
from odoo.tools import consteq


class DgtPortal(http.Controller):
    def _get_case(self, case_id, token):
        case = request.env["dgt.case"].sudo().browse(case_id).exists()
        if not case:
            return None
        if token and case.access_token and consteq(token, case.access_token):
            return case
        user = request.env.user
        if not user._is_public() and user.partner_id == case.partner_id:
            return case
        return None

    @http.route("/my/dgt/<int:case_id>", type="http", auth="public", website=True, methods=["GET", "POST"], sitemap=False)
    def dgt_case(self, case_id, access_token=None, **post):
        case = self._get_case(case_id, access_token)
        if not case:
            return request.not_found()

        error = None
        if request.httprequest.method == "POST" and case.state == "pending":
            try:
                case.write(
                    {
                        "owner_vat": (post.get("owner_vat") or "").strip().upper(),
                        "serial_number": (post.get("serial_number") or "").strip(),
                        "consent_gestoria": post.get("consent_gestoria") == "on",
                    }
                )
                case.action_submit_data()
            except (UserError, ValidationError) as exc:
                request.env.cr.rollback()
                error = exc.args[0] if exc.args else _("No se han podido guardar los datos.")
                case = case.with_env(request.env(su=True)).browse(case.id)

        return request.render(
            "moviraider_dgt.portal_dgt_case",
            {"case": case, "token": access_token, "error": error, "post": post},
        )

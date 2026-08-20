"""Member-only discovery of anonymously contributed Comunity Set settings."""

from flask import jsonify, redirect, render_template, request

from services import LIGHTBURN_PALETTE_NAMES, query_laser_community

from . import routes
from ._job_access import authenticated_user_id, authentication_state


@routes.route("/community-set")
def community_set():
    auth = authentication_state()
    return render_template(
        "community_set.html", official_colors=LIGHTBURN_PALETTE_NAMES,
        member_access=auth["signed_in"], auth_state=auth["state"],
    )


@routes.route("/laser-community")
def legacy_laser_community():
    return redirect("/community-set", code=301)


@routes.route("/laser-community/settings")
@routes.route("/community-set/settings")
def community_set_settings():
    if not authenticated_user_id():
        return jsonify({
            "status": "error",
            "message": "Sign in or create an account to access Comunity Set settings.",
        }), 401
    laser = request.args.get("laser", "").strip()
    lens = request.args.get("lens", "").strip()
    material = request.args.get("material", "").strip()
    color = request.args.get("color", "").strip()
    if any(len(value) > 160 for value in (laser, lens, material, color)):
        return jsonify({"status": "error", "message": "Filter values must be 160 characters or fewer."}), 400
    try:
        rows = query_laser_community(laser, lens, material, color)
        return jsonify({"status": "ok", "count": len(rows), "settings": rows})
    except (RuntimeError, ValueError) as error:
        return jsonify({"status": "error", "message": str(error)}), 400

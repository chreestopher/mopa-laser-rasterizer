"""Public, anonymous Comunity Set setting discovery."""

from flask import jsonify, redirect, render_template, request

from services import LIGHTBURN_PALETTE_NAMES, query_laser_community

from . import routes


@routes.route("/community-set")
def community_set():
    return render_template("community_set.html", official_colors=LIGHTBURN_PALETTE_NAMES)


@routes.route("/laser-community")
def legacy_laser_community():
    return redirect("/community-set", code=301)


@routes.route("/laser-community/settings")
@routes.route("/community-set/settings")
def community_set_settings():
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

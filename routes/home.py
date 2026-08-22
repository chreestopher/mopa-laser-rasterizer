"""Home, sign-in, and account-status routes."""

from urllib.parse import urlencode

from flask import current_app, jsonify, redirect, render_template, request

from services import LIGHTBURN_PALETTE_NAMES

from . import routes
from ._job_access import (
    authentication_state,
    clear_authenticated_browser_expectation,
    issue_submission_auth_token,
    remember_authenticated_browser,
)


@routes.before_app_request
def retain_account_expectation():
    """Remember authenticated browsers without treating header loss as logout."""
    remember_authenticated_browser()


@routes.route("/")
def index():
    return render_template(
        "index.html",
        canonical=f"{_public_url()}/",
        submission_auth_token=issue_submission_auth_token(),
    )


def _public_url():
    return (current_app.config.get("PUBLIC_APP_URL") or
            f"{request.scheme}://{request.host}").rstrip("/")


@routes.route("/color-laser-engraving-tool")
def color_laser_engraving_tool():
    return render_template(
        "color_laser_engraving_tool.html",
        canonical=f"{_public_url()}/color-laser-engraving-tool",
    )


@routes.route("/laser-engraving-tool")
def laser_engraving_tool():
    return render_template(
        "laser_engraving_tool.html",
        canonical=f"{_public_url()}/laser-engraving-tool",
    )


@routes.route("/founding-sponsors")
def founding_sponsors():
    """Recognize the manufacturers supporting the project's early growth."""
    # Add confirmed sponsors here. Keeping the records structured makes it
    # straightforward to add logos, links, supplied libraries, and materials
    # without redesigning the page.
    sponsors = []
    return render_template(
        "founding_sponsors.html",
        canonical=f"{_public_url()}/founding-sponsors",
        sponsors=sponsors,
    )


@routes.route("/depthmap-generator")
def depthmap_generator():
    """Unlisted, client-side experimental depth-map workspace."""
    depth_palette = [
        {"name": name, "hex": color_hex}
        for color_hex, name in LIGHTBURN_PALETTE_NAMES.items()
    ]
    return render_template(
        "depthmap_generator.html",
        canonical=f"{_public_url()}/depthmap-generator",
        depth_palette=depth_palette,
    )


@routes.route("/login")
def login():
    """ALB authenticates this route before returning users to the app home."""
    return render_template("login_complete.html")


@routes.route("/auth-status")
def auth_status():
    """Expose the account, guest, or reconnect state needed by the UI."""
    response = jsonify(authentication_state())
    response.headers["Cache-Control"] = "no-store"
    return response


@routes.route("/logout")
def logout():
    """Clear ALB's auth session and finish the Cognito hosted-UI sign-out flow."""
    clear_authenticated_browser_expectation()
    public_url = _public_url()
    cognito_domain = current_app.config.get("COGNITO_DOMAIN")
    client_id = current_app.config.get("COGNITO_CLIENT_ID")
    if cognito_domain and client_id:
        destination = f"https://{cognito_domain}/logout?" + urlencode({
            "client_id": client_id,
            "logout_uri": f"{public_url}/",
        })
    else:
        destination = "/"
    response = redirect(destination)
    # ALB may split a large session across numbered cookies.  The pod receives
    # ALB traffic over HTTP even though the browser used HTTPS, so this must
    # explicitly be Secure.  Otherwise Chrome rejects the SameSite=None
    # deletion response and leaves the ALB login session in place.
    # The ALB can strip its cookies before proxying to us, so do not rely on
    # ``request.cookies`` to reveal the chunk names.  ALB supports up to 11
    # chunks; expire every possible member of its default cookie family.
    session_cookie_names = {"AWSELBAuthSessionCookie"}
    session_cookie_names.update(
        f"AWSELBAuthSessionCookie-{chunk}" for chunk in range(11)
    )
    for cookie_name in session_cookie_names:
        response.delete_cookie(cookie_name, path="/", secure=True, samesite="None")
    return response


@routes.route("/holographic-etching")
def holographic_etching():
    """Dedicated workspace for the structural-color engraving workflow."""
    palette = [
        [name.lower(), color_hex]
        for color_hex, name in LIGHTBURN_PALETTE_NAMES.items()
    ]
    return render_template(
        "holographic_etching.html",
        lightburn_palette=palette,
        submission_auth_token=issue_submission_auth_token(),
    )


@routes.route("/material-libraries")
def material_library_manager():
    depth_palette = [
        {"name": name, "hex": color_hex}
        for color_hex, name in LIGHTBURN_PALETTE_NAMES.items()
    ]
    return render_template("material_libraries.html", depth_palette=depth_palette)

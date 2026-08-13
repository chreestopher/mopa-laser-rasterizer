"""Home, sign-in, and account-status routes."""

from urllib.parse import urlencode

from flask import current_app, jsonify, redirect, render_template, request

from . import routes


@routes.route("/")
def index():
    return current_app.send_static_file("index.html")


@routes.route("/login")
def login():
    """ALB authenticates this route before returning users to the app home."""
    return render_template("login_complete.html")


@routes.route("/auth-status")
def auth_status():
    """Expose only the ALB-authenticated state needed by the console chrome."""
    return jsonify({"signed_in": bool(request.headers.get("x-amzn-oidc-identity", "").strip())})


@routes.route("/logout")
def logout():
    """Clear ALB's auth session and finish the Cognito hosted-UI sign-out flow."""
    public_url = current_app.config.get("PUBLIC_APP_URL") or f"{request.scheme}://{request.host}"
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
    session_cookie_names = {"AWSELBAuthSessionCookie"}
    session_cookie_names.update(
        cookie_name for cookie_name in request.cookies
        if cookie_name.startswith("AWSELBAuthSessionCookie-")
    )
    for cookie_name in session_cookie_names:
        response.delete_cookie(cookie_name, path="/", secure=True, samesite="None")
    return response


@routes.route("/holographic-etching")
def holographic_etching():
    """Dedicated workspace for the structural-color engraving workflow."""
    return render_template("holographic_etching.html")

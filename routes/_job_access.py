"""Signed browser-session ownership and authentication-intent helpers."""

import hashlib
import uuid

from flask import current_app, request, session
from itsdangerous import BadSignature, URLSafeSerializer

from services import (
    claim_history_session,
    history_access_allowed,
    job_access_allowed,
    valid_history_session,
)


JOB_ACCESS_SESSION_KEY = "job_access_session"
ACCOUNT_EXPECTATION_SESSION_KEY = "account_auth_expectation"
SUBMISSION_AUTH_SALT = "rasterizer-submission-auth-v1"


def authenticated_user_id():
    """Return the identity asserted by the trusted authentication proxy."""
    return request.headers.get("x-amzn-oidc-identity", "").strip()


def _identity_digest(user_id):
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()


def remember_authenticated_browser(user_id=None):
    """Remember, in Flask's signed session, that this browser expects an account."""
    user_id = (user_id if user_id is not None else authenticated_user_id()).strip()
    if not user_id:
        return None
    marker = {"identity": _identity_digest(user_id)}
    if session.get(ACCOUNT_EXPECTATION_SESSION_KEY) != marker:
        session[ACCOUNT_EXPECTATION_SESSION_KEY] = marker
    return marker


def clear_authenticated_browser_expectation():
    """Make an explicit logout return this browser to ordinary guest mode."""
    session.pop(ACCOUNT_EXPECTATION_SESSION_KEY, None)


def authentication_state():
    """Return authenticated, guest, or reauthentication-required browser state."""
    user_id = authenticated_user_id()
    if user_id:
        remember_authenticated_browser(user_id)
        return {"state": "authenticated", "signed_in": True}
    marker = session.get(ACCOUNT_EXPECTATION_SESSION_KEY)
    if isinstance(marker, dict) and marker.get("identity"):
        return {"state": "reauth_required", "signed_in": False}
    return {"state": "guest", "signed_in": False}


def _submission_serializer():
    return URLSafeSerializer(current_app.secret_key, salt=SUBMISSION_AUTH_SALT)


def issue_submission_auth_token():
    """Bind a rendered form to the account/guest intent observed by the server."""
    state = authentication_state()
    marker = session.get(ACCOUNT_EXPECTATION_SESSION_KEY) or {}
    payload = {
        "mode": "guest" if state["state"] == "guest" else "account",
        "identity": marker.get("identity") if state["state"] != "guest" else None,
    }
    return _submission_serializer().dumps(payload)


def validate_submission_auth(token, allow_explicit_guest=False):
    """Return ``(user_id, error)`` without silently downgrading account intent."""
    user_id = authenticated_user_id()
    marker = session.get(ACCOUNT_EXPECTATION_SESSION_KEY)
    expected_identity = marker.get("identity") if isinstance(marker, dict) else None
    if not token:
        return user_id, {
            "code": "invalid_auth_context",
            "message": "This form predates the current security flow. Refresh the page before submitting; your files may need to be selected again.",
            "status": 400,
        }
    try:
        payload = _submission_serializer().loads(token)
    except BadSignature:
        return user_id, {
            "code": "invalid_auth_context",
            "message": "This form's security context is no longer valid. Refresh the page and try again.",
            "status": 400,
        }

    token_expects_account = isinstance(payload, dict) and payload.get("mode") == "account"
    token_identity = payload.get("identity") if token_expects_account else None
    if user_id:
        current_identity = _identity_digest(user_id)
        remember_authenticated_browser(user_id)
        if token_identity and token_identity != current_identity:
            return user_id, {
                "code": "account_changed",
                "message": "The signed-in account changed after this form was opened. Refresh before submitting so saved resources cannot cross accounts.",
                "status": 409,
            }
        return user_id, None

    account_expected = bool(expected_identity or token_expects_account)
    if account_expected and not allow_explicit_guest:
        return "", {
            "code": "reauthentication_required",
            "message": "Your account session needs to be reconnected before this job can be submitted. Your completed form can remain open while you sign in.",
            "status": 409,
        }
    return "", None


def browser_job_session(create=False):
    """Return the unforgeable ID carried inside Flask's signed session cookie."""
    session_id = valid_history_session(session.get(JOB_ACCESS_SESSION_KEY))
    if not session_id and create:
        session_id = str(uuid.uuid4())
        session[JOB_ACCESS_SESSION_KEY] = session_id
    return session_id


def private_history_session(candidate=None):
    """Claim a display/history ID for the current signed browser session."""
    return claim_history_session(candidate, browser_job_session(create=True))


def request_can_access_history(history_session):
    return history_access_allowed(history_session, browser_job_session())


def request_can_access_job(task_id):
    return job_access_allowed(
        task_id,
        user_id=request.headers.get("x-amzn-oidc-identity", "").strip(),
        browser_session=browser_job_session(),
    )

"""Signed browser-session ownership helpers for guest job routes."""

import uuid

from flask import request, session

from services import (
    claim_history_session,
    history_access_allowed,
    job_access_allowed,
    valid_history_session,
)


JOB_ACCESS_SESSION_KEY = "job_access_session"


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

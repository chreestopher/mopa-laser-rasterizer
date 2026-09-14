"""Private operational console restricted to one configured Cognito account."""

import base64
import hmac
import json
import os
import secrets

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError
from botocore.exceptions import ClientError
from flask import abort, jsonify, render_template, request, session

from services import (
    AWS_REGION,
    delete_queued_admin_job,
    list_admin_jobs,
    redis_client,
)

from . import routes


def _identity_claims():
    token = request.headers.get("x-amzn-oidc-data", "").strip()
    identity = request.headers.get("x-amzn-oidc-identity", "").strip()
    if not token or not identity:
        return None
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
    except (IndexError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not hmac.compare_digest(str(claims.get("sub") or ""), identity):
        return None
    return claims


def _require_admin():
    configured = os.environ.get("ADMIN_EMAIL", "").strip().casefold()
    claims = _identity_claims()
    email = str((claims or {}).get("email") or "").strip().casefold()
    email_verified = (claims or {}).get("email_verified") in (True, "true", "True")
    if (not configured or not email or not email_verified or
            not hmac.compare_digest(email, configured)):
        abort(404)
    return claims


def _csrf_token():
    token = session.get("admin_csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["admin_csrf"] = token
    return token


def _require_csrf():
    expected = str(session.get("admin_csrf") or "")
    supplied = request.headers.get("X-Admin-CSRF", "")
    if not expected or not hmac.compare_digest(expected, supplied):
        abort(403)


def _cognito_users():
    cache_key = "admin:cognito-users"
    cached = redis_client.get(cache_key)
    if cached:
        try:
            return json.loads(cached)
        except (TypeError, json.JSONDecodeError):
            pass
    pool_id = os.environ.get("COGNITO_POOL_ID", "").strip()
    if not pool_id:
        return None
    client = boto3.client(
        "cognito-idp", region_name=AWS_REGION,
        config=Config(connect_timeout=3, read_timeout=5,
                      retries={"max_attempts": 1, "mode": "standard"}),
    )
    users, token = [], None
    while True:
        kwargs = {"UserPoolId": pool_id, "Limit": 60}
        if token:
            kwargs["PaginationToken"] = token
        try:
            response = client.list_users(**kwargs)
        except (ClientError, BotoCoreError):
            return None
        for user in response.get("Users", []):
            attributes = {item["Name"]: item["Value"] for item in user.get("Attributes", [])}
            users.append({
                "email": attributes.get("email", ""),
                "status": user.get("UserStatus", ""),
                "enabled": bool(user.get("Enabled")),
                "created_at": user.get("UserCreateDate").isoformat() if user.get("UserCreateDate") else "",
            })
        token = response.get("PaginationToken")
        if not token:
            break
    users = sorted(users, key=lambda item: item["created_at"], reverse=True)
    redis_client.set(cache_key, json.dumps(users), ex=300)
    return users


@routes.route("/admin")
def admin_console():
    claims = _require_admin()
    try:
        jobs = list_admin_jobs(days=7)
    except Exception:
        abort(503)
    return render_template(
        "admin.html", jobs=jobs,
        admin_email=claims.get("email", ""), csrf_token=_csrf_token(),
    )


@routes.route("/admin/users")
def admin_users():
    _require_admin()
    users = _cognito_users()
    response = jsonify({
        "status": "ok" if users is not None else "unavailable",
        "count": len(users) if users is not None else None,
        "users": users or [],
    })
    response.headers["Cache-Control"] = "no-store"
    return response


@routes.route("/admin/jobs/<task_id>/logs")
def admin_job_logs(task_id):
    _require_admin()
    logs = redis_client.lrange(f"task:{task_id}:log", 0, -1)
    status = redis_client.get(f"task:{task_id}:status") or "unknown"
    response = jsonify({"task_id": task_id, "status": status, "logs": logs})
    response.headers["Cache-Control"] = "no-store"
    return response


@routes.route("/admin/jobs/<task_id>/queue", methods=["DELETE"])
def admin_delete_queued_job(task_id):
    _require_admin()
    _require_csrf()
    if not delete_queued_admin_job(task_id):
        return jsonify({
            "status": "error",
            "message": "This job is not waiting in the queue; running jobs are not deleted here.",
        }), 409
    return jsonify({"status": "ok", "message": "Job removed from the waiting queue."})

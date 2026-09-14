import base64
import json
from pathlib import Path

from flask import Flask

import routes.admin as admin
from routes import routes


def identity_headers(email="owner@example.com", subject="admin-subject"):
    def encoded(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
    token = f"{encoded({'alg': 'ES256'})}.{encoded({'sub': subject, 'email': email, 'email_verified': True})}.signature"
    return {"x-amzn-oidc-identity": subject, "x-amzn-oidc-data": token}


def app_client():
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).resolve().parents[1] / "templates"),
        static_folder=str(Path(__file__).resolve().parents[1] / "static"),
    )
    app.secret_key = "test-secret"
    app.register_blueprint(routes)
    return app.test_client()


def test_admin_is_default_deny(monkeypatch):
    monkeypatch.delenv("ADMIN_EMAIL", raising=False)
    response = app_client().get("/admin", headers=identity_headers())
    assert response.status_code == 404


def test_admin_rejects_another_signed_in_email(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", "owner@example.com")
    response = app_client().get(
        "/admin", headers=identity_headers(email="someone@example.com")
    )
    assert response.status_code == 404


def test_admin_renders_for_matching_email(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", "OWNER@example.com")
    monkeypatch.setattr(admin, "list_admin_jobs", lambda days=7: [])
    monkeypatch.setattr(admin, "_cognito_users", lambda: [])
    response = app_client().get("/admin", headers=identity_headers())
    assert response.status_code == 200
    assert b"Seven-day job activity" in response.data


def test_queue_delete_requires_csrf(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", "owner@example.com")
    response = app_client().delete(
        "/admin/jobs/example/queue", headers=identity_headers()
    )
    assert response.status_code == 403


def test_user_directory_is_loaded_separately(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", "owner@example.com")
    monkeypatch.setattr(admin, "_cognito_users", lambda: [{
        "email": "member@example.com", "status": "CONFIRMED",
        "enabled": True, "created_at": "2026-08-23T00:00:00",
    }])
    response = app_client().get("/admin/users", headers=identity_headers())
    assert response.status_code == 200
    assert response.get_json()["count"] == 1

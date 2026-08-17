import unittest

from flask import Flask, jsonify, request

from routes._job_access import (
    authentication_state,
    clear_authenticated_browser_expectation,
    issue_submission_auth_token,
    validate_submission_auth,
)


class AuthenticationIntentTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config["SECRET_KEY"] = "authentication-intent-test-secret"

        @app.get("/status")
        def status():
            return jsonify(authentication_state())

        @app.get("/token")
        def token():
            return issue_submission_auth_token()

        @app.post("/validate")
        def validate():
            user_id, error = validate_submission_auth(
                request.form.get("token", ""),
                allow_explicit_guest=request.form.get("guest") == "1",
            )
            if error:
                return jsonify(error), error["status"]
            return jsonify({"user_id": user_id, "mode": "account" if user_id else "guest"})

        @app.post("/logout-marker")
        def logout_marker():
            clear_authenticated_browser_expectation()
            return "ok"

        self.client = app.test_client()

    def test_new_browser_is_an_ordinary_guest(self):
        self.assertEqual("guest", self.client.get("/status").get_json()["state"])

    def test_missing_header_after_authentication_requires_reconnection(self):
        authenticated = self.client.get(
            "/status", headers={"x-amzn-oidc-identity": "account-a"},
        ).get_json()
        self.assertEqual("authenticated", authenticated["state"])
        self.assertEqual("reauth_required", self.client.get("/status").get_json()["state"])

    def test_explicit_logout_returns_browser_to_guest_mode(self):
        self.client.get("/status", headers={"x-amzn-oidc-identity": "account-a"})
        self.client.post("/logout-marker")
        self.assertEqual("guest", self.client.get("/status").get_json()["state"])

    def test_account_form_cannot_silently_downgrade_to_guest(self):
        token = self.client.get(
            "/token", headers={"x-amzn-oidc-identity": "account-a"},
        ).get_data(as_text=True)
        response = self.client.post("/validate", data={"token": token})
        self.assertEqual(409, response.status_code)
        self.assertEqual("reauthentication_required", response.get_json()["code"])

    def test_legacy_form_without_signed_context_must_refresh(self):
        response = self.client.post("/validate")
        self.assertEqual(400, response.status_code)
        self.assertEqual("invalid_auth_context", response.get_json()["code"])

    def test_user_can_explicitly_continue_an_account_form_as_guest(self):
        token = self.client.get(
            "/token", headers={"x-amzn-oidc-identity": "account-a"},
        ).get_data(as_text=True)
        response = self.client.post("/validate", data={"token": token, "guest": "1"})
        self.assertEqual(200, response.status_code)
        self.assertEqual("guest", response.get_json()["mode"])

    def test_same_account_can_reconnect_and_submit_original_form(self):
        token = self.client.get(
            "/token", headers={"x-amzn-oidc-identity": "account-a"},
        ).get_data(as_text=True)
        response = self.client.post(
            "/validate",
            data={"token": token},
            headers={"x-amzn-oidc-identity": "account-a"},
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual("account", response.get_json()["mode"])

    def test_switching_accounts_requires_a_fresh_form(self):
        token = self.client.get(
            "/token", headers={"x-amzn-oidc-identity": "account-a"},
        ).get_data(as_text=True)
        response = self.client.post(
            "/validate",
            data={"token": token},
            headers={"x-amzn-oidc-identity": "account-b"},
        )
        self.assertEqual(409, response.status_code)
        self.assertEqual("account_changed", response.get_json()["code"])


if __name__ == "__main__":
    unittest.main()

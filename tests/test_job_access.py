import unittest
from unittest.mock import patch

from flask import Flask

import services
from routes._job_access import browser_job_session


TASK_ID = "11111111-1111-4111-8111-111111111111"
BROWSER_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
BROWSER_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
HISTORY_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.expirations = {}

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.values:
            return False
        self.values[key] = value
        if ex is not None:
            self.expirations[key] = ex
        return True

    def get(self, key):
        return self.values.get(key)

    def expire(self, key, seconds):
        if key not in self.values:
            return False
        self.expirations[key] = seconds
        return True


class JobAccessTests(unittest.TestCase):
    def setUp(self):
        self.redis = FakeRedis()
        self.redis_patch = patch.object(services, "redis_client", self.redis)
        self.owner_patch = patch.object(services, "get_job_owner", return_value=None)
        self.redis_patch.start()
        self.owner_patch.start()

    def tearDown(self):
        self.owner_patch.stop()
        self.redis_patch.stop()

    def test_guest_job_requires_the_bound_browser_session(self):
        services.bind_job_access(TASK_ID, browser_session=BROWSER_A)

        self.assertTrue(services.job_access_allowed(TASK_ID, browser_session=BROWSER_A))
        self.assertFalse(services.job_access_allowed(TASK_ID, browser_session=BROWSER_B))
        self.assertFalse(services.job_access_allowed(TASK_ID))

    def test_account_binding_rejects_guests_and_other_accounts(self):
        services.bind_job_access(TASK_ID, user_id="account-a")

        self.assertTrue(services.job_access_allowed(TASK_ID, user_id="account-a"))
        self.assertFalse(services.job_access_allowed(TASK_ID, user_id="account-b"))
        self.assertFalse(services.job_access_allowed(TASK_ID, browser_session=BROWSER_A))

    def test_durable_account_owner_is_authoritative(self):
        services.bind_job_access(TASK_ID, browser_session=BROWSER_A)

        with patch.object(services, "get_job_owner", return_value="account-a"):
            self.assertTrue(services.job_access_allowed(TASK_ID, user_id="account-a"))
            self.assertFalse(services.job_access_allowed(TASK_ID, browser_session=BROWSER_A))

    def test_job_without_an_owner_binding_fails_closed(self):
        self.assertFalse(services.job_access_allowed(TASK_ID, browser_session=BROWSER_A))

    def test_history_id_cannot_be_claimed_by_another_browser(self):
        claimed_a = services.claim_history_session(HISTORY_ID, BROWSER_A)
        claimed_b = services.claim_history_session(HISTORY_ID, BROWSER_B)

        self.assertEqual(HISTORY_ID, claimed_a)
        self.assertNotEqual(HISTORY_ID, claimed_b)
        self.assertTrue(services.history_access_allowed(HISTORY_ID, BROWSER_A))
        self.assertFalse(services.history_access_allowed(HISTORY_ID, BROWSER_B))
        self.assertTrue(services.history_access_allowed(claimed_b, BROWSER_B))

    def test_signed_browser_identity_persists_and_is_not_shared(self):
        app = Flask(__name__)
        app.config["SECRET_KEY"] = "job-access-test-secret"

        @app.get("/browser-session")
        def show_browser_session():
            return browser_job_session(create=True)

        first_browser = app.test_client()
        second_browser = app.test_client()
        first_id = first_browser.get("/browser-session").get_data(as_text=True)

        self.assertEqual(first_id, first_browser.get("/browser-session").get_data(as_text=True))
        self.assertNotEqual(first_id, second_browser.get("/browser-session").get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()

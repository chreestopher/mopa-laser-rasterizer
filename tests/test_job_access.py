import json
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

    def test_browser_history_excludes_jobs_the_requester_cannot_access(self):
        visible_job = {"task_id": TASK_ID, "source_name": "mine.png"}
        hidden_job = {
            "task_id": "22222222-2222-4222-8222-222222222222",
            "source_name": "another-account.png",
        }
        with (
            patch.object(
                services, "get_history_entries", return_value=[visible_job, hidden_job],
            ),
            patch.object(
                services, "job_access_allowed", side_effect=[True, False],
            ) as access_allowed,
        ):
            entries = services.get_accessible_history_entries(
                HISTORY_ID, user_id="account-a", browser_session=BROWSER_A,
            )

        self.assertEqual([visible_job], entries)
        self.assertEqual(2, access_allowed.call_count)
        access_allowed.assert_any_call(
            TASK_ID, user_id="account-a", browser_session=BROWSER_A,
        )

    def test_logged_out_browser_history_hides_account_owned_jobs(self):
        account_job = {"task_id": TASK_ID, "source_name": "account.png"}
        with patch.object(services, "get_history_entries", return_value=[account_job]):
            with patch.object(services, "get_job_owner", return_value="account-a"):
                entries = services.get_accessible_history_entries(
                    HISTORY_ID, browser_session=BROWSER_A,
                )

        self.assertEqual([], entries)

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

    def test_guest_browser_can_retain_and_select_multiple_material_libraries(self):
        first = services.remember_guest_material_library(HISTORY_ID, {
            "filename": "polished-steel.clb",
            "path": "C:/work/polished-steel.clb",
            "key": "guest/jobs/one/inputs/polished-steel.clb",
            "created_at": 10,
        })
        second = services.remember_guest_material_library(HISTORY_ID, {
            "filename": "brushed-steel.clb",
            "path": "C:/work/brushed-steel.clb",
            "key": "guest/jobs/two/inputs/brushed-steel.clb",
            "created_at": 20,
        })

        listed = services.list_guest_material_libraries(HISTORY_ID)
        self.assertEqual(
            [second["library_id"], first["library_id"]],
            [library["library_id"] for library in listed],
        )
        self.assertNotIn("path", listed[0])
        self.assertNotIn("key", listed[0])

        selected = services.select_guest_material_library(HISTORY_ID, first["library_id"])
        self.assertEqual("polished-steel.clb", selected["filename"])
        current = json.loads(self.redis.get(f"material-library:{HISTORY_ID}"))
        self.assertEqual(first["library_id"], current["library_id"])


if __name__ == "__main__":
    unittest.main()

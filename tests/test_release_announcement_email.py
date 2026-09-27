import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "dev_setup" / "release_announcement_email.py"
SPEC = importlib.util.spec_from_file_location("release_announcement_email", SCRIPT)
release_email = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_email)


class PagedCognito:
    def __init__(self):
        self.calls = []

    def list_users(self, **request):
        self.calls.append(request)
        if "PaginationToken" not in request:
            return {
                "Users": [
                    {
                        "Enabled": True,
                        "UserStatus": "CONFIRMED",
                        "Attributes": [
                            {"Name": "email", "Value": "Member@Example.com"},
                            {"Name": "email_verified", "Value": "true"},
                        ],
                    },
                    {
                        "Enabled": True,
                        "UserStatus": "UNCONFIRMED",
                        "Attributes": [
                            {"Name": "email", "Value": "unconfirmed@example.com"},
                            {"Name": "email_verified", "Value": "true"},
                        ],
                    },
                ],
                "PaginationToken": "page-2",
            }
        return {
            "Users": [
                {
                    "Enabled": True,
                    "UserStatus": "CONFIRMED",
                    "Attributes": [
                        {"Name": "email", "Value": "second@example.com"},
                        {"Name": "email_verified", "Value": "true"},
                    ],
                },
                {
                    "Enabled": False,
                    "UserStatus": "CONFIRMED",
                    "Attributes": [
                        {"Name": "email", "Value": "disabled@example.com"},
                        {"Name": "email_verified", "Value": "true"},
                    ],
                },
            ]
        }


class PagedContacts:
    def __init__(self):
        self.calls = []

    def list_contacts(self, **request):
        self.calls.append(request)
        if "NextToken" not in request:
            return {
                "Contacts": [
                    {
                        "EmailAddress": "member@example.com",
                        "TopicPreferences": [{"TopicName": "releases", "SubscriptionStatus": "OPT_IN"}],
                    },
                    {
                        "EmailAddress": "default-only@example.com",
                        "TopicDefaultPreferences": [{"TopicName": "releases", "SubscriptionStatus": "OPT_IN"}],
                    },
                ],
                "NextToken": "page-2",
            }
        return {
            "Contacts": [
                {
                    "EmailAddress": "second@example.com",
                    "UnsubscribeAll": True,
                    "TopicPreferences": [{"TopicName": "releases", "SubscriptionStatus": "OPT_IN"}],
                }
            ]
        }


class FakeSes:
    def __init__(self, failures=None):
        self.calls = []
        self.failures = list(failures or [])

    def send_email(self, **request):
        self.calls.append(request)
        if self.failures:
            raise self.failures.pop(0)
        return {"MessageId": f"message-{len(self.calls)}"}


class AwsError(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}


@pytest.fixture
def approved_announcement():
    data = json.loads((ROOT / "docs" / "releases" / "current-announcement.json").read_text(encoding="utf-8"))
    data["status"] = "approved"
    data["intro"] = "Use <safe> rendering & escaping."
    return data


def test_render_has_plain_and_html_unsubscribe_and_escapes(approved_announcement):
    rendered = release_email.render_announcement(approved_announcement)

    assert rendered.text.count(release_email.UNSUBSCRIBE_URL) == 1
    assert rendered.html.count(release_email.UNSUBSCRIBE_URL) == 1
    assert "Use &lt;safe&gt; rendering &amp; escaping." in rendered.html
    assert "Use <safe> rendering & escaping." in rendered.text
    assert rendered.campaign_id.startswith("next-production-release-")


def test_cognito_enumeration_paginates_and_requires_confirmed_verified_enabled():
    client = PagedCognito()

    assert list(release_email.cognito_member_emails(client, "pool-123")) == [
        "member@example.com", "second@example.com",
    ]
    assert client.calls == [
        {"UserPoolId": "pool-123", "Limit": 60},
        {"UserPoolId": "pool-123", "Limit": 60, "PaginationToken": "page-2"},
    ]


def test_ses_contacts_paginate_and_require_explicit_topic_opt_in():
    client = PagedContacts()

    assert list(release_email.opted_in_contact_emails(client, "members", "releases")) == [
        "member@example.com"
    ]
    assert client.calls[0]["Filter"]["TopicFilter"]["UseDefaultIfPreferenceUnavailable"] is False
    assert client.calls[1]["NextToken"] == "page-2"


def test_recipient_selection_deduplicates_intersects_and_suppresses():
    selected = release_email.select_recipients(
        ["ONE@example.com", "one@example.com", "two@example.com", "bad address"],
        ["one@example.com", "two@example.com", "not-a-member@example.com"],
        ["TWO@example.com"],
    )
    assert selected == ["one@example.com"]


def test_send_is_single_recipient_list_managed_and_idempotent(tmp_path, approved_announcement):
    rendered = release_email.render_announcement(approved_announcement)
    audit = tmp_path / "audit.jsonl"
    ses = FakeSes()

    summary = release_email.send_campaign(
        ses=ses,
        recipients=["one@example.com", "two@example.com"],
        rendered=rendered,
        source="sender@example.com",
        contact_list="members",
        topic="releases",
        configuration_set="release-events",
        audit_path=audit,
        audit_secret="x" * 32,
        messages_per_second=1000,
        batch_size=25,
        sleep=lambda _: None,
    )

    assert summary == {"sent": 2, "failed": 0, "skipped": 0}
    assert all(len(call["Destination"]["ToAddresses"]) == 1 for call in ses.calls)
    assert all(call["ListManagementOptions"] == {
        "ContactListName": "members", "TopicName": "releases"
    } for call in ses.calls)
    assert "one@example.com" not in audit.read_text(encoding="utf-8")

    second = release_email.send_campaign(
        ses=ses,
        recipients=["one@example.com", "two@example.com"],
        rendered=rendered,
        source="sender@example.com",
        contact_list="members",
        topic="releases",
        configuration_set="release-events",
        audit_path=audit,
        audit_secret="x" * 32,
        messages_per_second=1000,
        sleep=lambda _: None,
    )
    assert second == {"sent": 0, "failed": 0, "skipped": 2}
    assert len(ses.calls) == 2
    assert not Path(f"{audit}.lock").exists()

    with pytest.raises(release_email.ReleaseEmailError, match="HMAC key"):
        release_email.send_campaign(
            ses=ses, recipients=["one@example.com"], rendered=rendered,
            source="sender@example.com", contact_list="members", topic="releases",
            configuration_set="release-events", audit_path=audit,
            audit_secret="different-secret-value-that-is-long-enough",
            messages_per_second=1000, sleep=lambda _: None,
        )


def test_transient_errors_retry_but_permanent_errors_are_recorded(tmp_path, approved_announcement):
    rendered = release_email.render_announcement(approved_announcement)
    sleeps = []
    transient = FakeSes([AwsError("ThrottlingException")])

    retried = release_email.send_campaign(
        ses=transient, recipients=["one@example.com"], rendered=rendered,
        source="sender@example.com", contact_list="members", topic="releases",
        configuration_set="release-events", audit_path=tmp_path / "retry.jsonl",
        audit_secret="x" * 32, messages_per_second=1000, sleep=sleeps.append,
    )
    assert retried == {"sent": 1, "failed": 0, "skipped": 0}
    assert len(transient.calls) == 2
    assert 1 in sleeps

    permanent = FakeSes([AwsError("MessageRejected")])
    failed = release_email.send_campaign(
        ses=permanent, recipients=["two@example.com"], rendered=rendered,
        source="sender@example.com", contact_list="members", topic="releases",
        configuration_set="release-events", audit_path=tmp_path / "failure.jsonl",
        audit_secret="x" * 32, messages_per_second=1000, sleep=lambda _: None,
    )
    assert failed == {"sent": 0, "failed": 1, "skipped": 0}
    assert len(permanent.calls) == 1


def test_default_cli_is_preview_only_and_draft_cannot_send(tmp_path, capsys):
    assert release_email.main(["--preview-dir", str(tmp_path / "preview")]) == 0
    assert "no AWS clients were created" in capsys.readouterr().out
    assert (tmp_path / "preview" / "announcement.html").exists()

    data = release_email.load_announcement(release_email.DEFAULT_ANNOUNCEMENT)
    assert data["status"] == "draft"
    with pytest.raises(release_email.ReleaseEmailError, match="status 'approved'"):
        release_email.main([
            "--send", "--preview-dir", str(tmp_path / "send-preview"),
            "--user-pool-id", "pool", "--contact-list", "members", "--topic", "releases",
            "--source-email", "sender@example.com", "--configuration-set", "events",
            "--audit-log", str(tmp_path / "audit.jsonl"), "--expected-account-id", "123456789012",
        ])


def test_release_email_is_not_wired_into_deployment_workflows():
    deployment_files = [
        *ROOT.glob(".github/workflows/*"),
        ROOT / "dev_setup" / "deploy_serverless_staging_release.sh",
        ROOT / "dev_setup" / "deploy_serverless_production_release.sh",
    ]
    for path in deployment_files:
        if path.is_file():
            assert "release_announcement_email.py" not in path.read_text(encoding="utf-8")

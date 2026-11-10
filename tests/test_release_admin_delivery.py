"""Exercise the real delivery function without importing AWS clients."""
import ast
import secrets
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


class ClientError(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}


class Key:
    def __init__(self, name):
        pass

    def eq(self, value):
        return self

    def begins_with(self, value):
        return self

    def __and__(self, other):
        return self


class Table:
    def __init__(self, states, fail_success_record=False):
        self.states = dict(states)
        self.result = None
        self.pages = 0
        self.fail_success_record = fail_success_record

    def update_item(self, **request):
        values = request["ExpressionAttributeValues"]
        key = request["Key"]["sk"]
        if key == "campaign":
            if ":sent" in values:
                self.result = values
            return
        if ":attempting" in values:
            assert request["ConditionExpression"] == "attribute_not_exists(pk) OR #state=:failed"
            if key in self.states and self.states[key] != "failed":
                raise ClientError("ConditionalCheckFailedException")
            self.states[key] = "attempting"
        elif ":message" in values:
            if self.fail_success_record:
                raise ClientError("ProvisionedThroughputExceededException")
            self.states[key] = "sent"
        else:
            self.states[key] = "failed"

    def query(self, **request):
        self.pages += 1
        records = [{"state": state} for state in self.states.values()]
        if "ExclusiveStartKey" not in request and len(records) > 1:
            return {"Items": records[:1], "LastEvaluatedKey": {"sk": "next"}}
        return {"Items": records[1:] if "ExclusiveStartKey" in request else records}


def delivery(table, send, recipients):
    tree = ast.parse((Path(__file__).resolve().parents[1] / "serverless_api/handler.py").read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "deliver_release_announcement")
    namespace = {
        "table": table, "ClientError": ClientError, "Key": Key,
        "secrets": secrets, "time": time,
        "current_release_announcement": lambda: ({}, SimpleNamespace(campaign_id="release")),
        "release_campaign_key": lambda campaign: {"sk": "campaign"},
        "_release_recipient_key": lambda campaign, email: {"sk": email},
        "_release_recipients": lambda: recipients,
        "_send_release_email": send,
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), "handler.py", "exec"), namespace)
    return namespace["deliver_release_announcement"]("release")


def test_retry_sends_only_failed_and_new_recipients_and_counts_all_pages():
    table = Table({"sent": "sent", "retry": "failed"})
    calls = []
    def send(rendered, email):
        calls.append(email)
        return {"MessageId": email}
    result = delivery(table, send, ["sent", "retry", "new"])
    assert calls == ["retry", "new"]
    assert result["status"] == "sent"
    assert result["sent_count"] == 3
    assert table.pages == 2


def test_failure_can_be_retried_but_uncertain_attempt_is_skipped():
    table = Table({"uncertain": "attempting"})
    def fail(rendered, email):
        raise ClientError("MessageRejected")
    result = delivery(table, fail, ["retry", "uncertain"])
    assert table.states == {"uncertain": "attempting", "retry": "failed"}
    calls = []
    def send(rendered, email):
        calls.append(email)
        return {"MessageId": "accepted"}
    result = delivery(table, send, ["retry", "uncertain"])
    assert calls == ["retry"]
    assert result["sent_count"] == 1
    assert result["failed_count"] == 1


def test_failure_to_record_success_does_not_make_accepted_email_retryable():
    table = Table({}, fail_success_record=True)
    with pytest.raises(ClientError):
        delivery(table, lambda *_: {"MessageId": "accepted"}, ["recipient"])
    assert table.states["recipient"] == "attempting"
    calls = []
    delivery(table, lambda *args: calls.append(args), ["recipient"])
    assert calls == []

import ast
import hashlib
import json
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HANDLER_PATH = ROOT / "serverless_api" / "handler.py"


class FakeClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeTable:
    def __init__(self):
        self.fingerprints = set()
        self.updates = []

    def put_item(self, Item, ConditionExpression=None):
        key = (Item["pk"], Item["sk"])
        if key in self.fingerprints:
            raise FakeClientError("ConditionalCheckFailedException")
        self.fingerprints.add(key)

    def update_item(self, **kwargs):
        self.updates.append(kwargs)


class ServerlessUploadTelemetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = HANDLER_PATH.read_text(encoding="utf-8")
        module = ast.parse(cls.source)
        cls.function = next(
            node for node in module.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "record_artwork_duplicate_telemetry"
        )

    def namespace(self, table):
        namespace = {
            "ARTWORK_TELEMETRY_SECONDS": 30 * 86400,
            "ClientError": FakeClientError,
            "hashlib": hashlib,
            "json": json,
            "table": table,
            "time": time,
        }
        exec(
            compile(ast.Module(body=[self.function], type_ignores=[]), str(HANDLER_PATH), "exec"),
            namespace,
        )
        return namespace

    def test_first_upload_then_duplicate_updates_anonymous_daily_totals(self):
        table = FakeTable()
        record = self.namespace(table)["record_artwork_duplicate_telemetry"]
        head = {"ContentLength": 2048, "ETag": '"abc123"'}

        first = record("user-one", "task-one", head)
        second = record("user-one", "task-two", head)

        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        aggregate_updates = [
            call for call in table.updates
            if call["Key"]["pk"] == "TELEMETRY#ARTWORK_UPLOADS"
        ]
        self.assertEqual(2, len(aggregate_updates))
        self.assertEqual(0, aggregate_updates[0]["ExpressionAttributeValues"][":duplicate"])
        self.assertEqual(1, aggregate_updates[1]["ExpressionAttributeValues"][":duplicate"])
        self.assertEqual(2048, aggregate_updates[1]["ExpressionAttributeValues"][":duplicate_bytes"])

    def test_same_artwork_is_scoped_per_user(self):
        table = FakeTable()
        record = self.namespace(table)["record_artwork_duplicate_telemetry"]
        head = {"ContentLength": 500, "ETag": '"same-object"'}

        first_user = record("user-one", "task-one", head)
        other_user = record("user-two", "task-two", head)

        self.assertFalse(first_user["duplicate"])
        self.assertFalse(other_user["duplicate"])

    def test_invalid_head_never_blocks_job_path(self):
        record = self.namespace(FakeTable())["record_artwork_duplicate_telemetry"]
        self.assertIsNone(record("user-one", "task-one", {}))

    def test_both_submission_paths_record_verified_artwork(self):
        self.assertIn(
            "record_artwork_duplicate_telemetry(user_id(event), task_id, artwork_head)",
            self.source,
        )
        self.assertIn(
            "record_artwork_duplicate_telemetry(owner, task_id, artwork_head)",
            self.source,
        )
        self.assertIn("if not guest:\n        record_artwork_duplicate_telemetry", self.source)
        self.assertIn("return head", self.source)


if __name__ == "__main__":
    unittest.main()

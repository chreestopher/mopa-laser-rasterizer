import importlib.util
import os
from pathlib import Path
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch


NOW = datetime(2026, 9, 16, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]


def item(key, etag='"one"', size=25):
    return {"Key": key, "ETag": etag, "LastModified": NOW, "Size": size}


class FakeS3:
    def __init__(self, source, destination=None):
        self.source = dict(source)
        self.destination = dict(destination or {})
        self.copies = []
        self.deletions = []

    def get_paginator(self, operation):
        assert operation == "list_objects_v2"
        return SimpleNamespace(paginate=self.paginate)

    def paginate(self, Bucket, Prefix):
        assert Prefix == "users/"
        entries = self.source if Bucket == "source" else self.destination
        yield {"Contents": list(entries.values())}

    def head_object(self, Bucket, Key):
        entry = (self.source if Bucket == "source" else self.destination)[Key]
        return {
            **entry,
            "Metadata": entry.get("Metadata", {}),
            "ContentType": "application/octet-stream",
            "VersionId": entry.get("VersionId", "v1"),
        }

    def copy_object(self, **request):
        self.copies.append(request)
        source = self.source[request["Key"]]
        self.destination[request["Key"]] = {**source, "Metadata": request["Metadata"]}

    def delete_object(self, Bucket, Key):
        assert Bucket == "destination"
        self.deletions.append(Key)
        del self.destination[Key]


def load_handler(fake_s3):
    with patch.dict(os.environ, {"SOURCE_BUCKET": "source", "BACKUP_BUCKET": "destination"}), patch.dict(
        sys.modules, {"boto3": SimpleNamespace(client=lambda _service: fake_s3)}
    ):
        spec = importlib.util.spec_from_file_location(
            "serverless_backup_under_test", ROOT / "serverless_backup" / "handler.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    return module


class ServerlessBackupTests(unittest.TestCase):
    def test_only_durable_user_prefixes_are_included(self):
        module = load_handler(FakeS3({}))
        self.assertTrue(module.durable_key("users/owner/materials/library/file.clb"))
        self.assertTrue(module.durable_key("users/owner/holographic-recipes/id/file.json"))
        self.assertTrue(module.durable_key("users/owner/holographic-calibrations/id/file.svg"))
        self.assertFalse(module.durable_key("users/owner/jobs/id/output.svg"))
        self.assertFalse(module.durable_key("users/owner/color-discovery/id/grid.json"))
        self.assertFalse(module.durable_key("jobs/id/output.svg"))

    def test_changed_objects_copy_and_missing_objects_are_versioned_deletes(self):
        unchanged = item("users/owner/materials/a/a.clb")
        changed = item("users/owner/holographic-recipes/b/b.json", '"new"')
        obsolete = item("users/owner/materials/old/old.clb")
        fake = FakeS3(
            {unchanged["Key"]: unchanged, changed["Key"]: changed},
            {
                unchanged["Key"]: {**unchanged, "Metadata": {
                    "backup-source-etag": "one", "backup-source-modified": NOW.isoformat()
                }},
                changed["Key"]: {**changed, "Metadata": {"backup-source-etag": "old"}},
                obsolete["Key"]: obsolete,
            },
        )
        result = load_handler(fake).handler({}, None)
        self.assertEqual(result["copied"], 1)
        self.assertEqual(result["deletions"], 1)
        self.assertEqual(fake.copies[0]["Key"], changed["Key"])
        self.assertEqual(fake.deletions, [obsolete["Key"]])

    def test_mass_deletion_guard_keeps_the_backup(self):
        destination = {
            f"users/owner/materials/{number}/file.clb": item(f"users/owner/materials/{number}/file.clb")
            for number in range(10)
        }
        source = dict(list(destination.items())[:2])
        fake = FakeS3(source, destination)
        with self.assertRaisesRegex(RuntimeError, "Too many"):
            load_handler(fake).handler({}, None)
        self.assertEqual(fake.deletions, [])
        self.assertEqual(fake.copies, [])

    def test_dry_run_does_not_write(self):
        key = "users/owner/materials/a/file.clb"
        fake = FakeS3({key: item(key)})
        result = load_handler(fake).handler({"dry_run": True}, None)
        self.assertEqual(result["copied"], 1)
        self.assertEqual(fake.copies, [])
        self.assertEqual(fake.deletions, [])


if __name__ == "__main__":
    unittest.main()

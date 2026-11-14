"""Exercise admin artifact authorization, job scoping, and signed downloads."""

import ast
from pathlib import Path
from unittest.mock import Mock

import pytest


ROOT = Path(__file__).resolve().parents[1]


def admin_api(record, *, denied=None, pages=None):
    names = {"admin_job", "ordered_output_descriptors", "output_descriptor",
             "raster_output_sort_key", "rasterized_download_name"}
    tree = ast.parse((ROOT / "serverless_api/handler.py").read_text(encoding="utf-8"))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    table = Mock()
    table.get_item.side_effect = [{"Item": record}, {"Item": {"source_name": "reported.png"}}]
    s3 = Mock()
    s3.list_objects_v2.side_effect = pages or [{}]
    s3.generate_presigned_url.return_value = "https://example.test/signed-output"
    namespace = {
        "require_admin": lambda event: denied,
        "table": table, "s3": s3, "BUCKET": "private-artifacts",
        "runtime": lambda task_id: {"status": "failed"},
        "job_logs": lambda *args: [], "visible_job_logs": lambda *args: [],
        "history_job_type": lambda record: "raster",
        "safe_name": lambda value, fallback: value or fallback,
        "response": lambda status, body: (status, body),
    }
    exec(compile(ast.Module(body=functions, type_ignores=[]), "admin-downloads", "exec"), namespace)
    return namespace["admin_job"], table, s3


def test_unauthorized_admin_request_never_reads_or_signs_artifacts():
    handler, table, s3 = admin_api({}, denied=(404, {"message": "Not found"}))
    assert handler({}, "task-1")[0] == 404
    table.get_item.assert_not_called()
    s3.list_objects_v2.assert_not_called()
    s3.generate_presigned_url.assert_not_called()


def test_missing_job_does_not_list_or_sign_artifacts():
    handler, _, s3 = admin_api(None)
    assert handler({}, "missing")[0] == 404
    s3.list_objects_v2.assert_not_called()
    s3.generate_presigned_url.assert_not_called()


@pytest.mark.parametrize("guest,prefix", [
    (False, "users/user-1/jobs/task-1/outputs/"),
    (True, "jobs/task-1/outputs/"),
])
def test_admin_can_download_failed_account_or_guest_job_outputs(guest, prefix):
    record = {"user_id": "user-1", "history_sk": "JOB#1", "guest": guest}
    handler, _, s3 = admin_api(record, pages=[{
        "Contents": [{"Key": prefix + name, "Size": 42}
                     for name in ("cooling.zip", "project.lbrn2", "artwork.svg")],
    }])
    status, body = handler({}, "task-1")
    assert status == 200
    assert body["status"] == "failed"
    assert [output["name"] for output in body["outputs"]] == ["artwork.svg", "project.lbrn2", "cooling.zip"]
    s3.list_objects_v2.assert_called_once_with(Bucket="private-artifacts", Prefix=prefix)
    for call in s3.generate_presigned_url.call_args_list:
        assert call.args == ("get_object",)
        assert call.kwargs["Params"]["Key"].startswith(prefix)
        assert call.kwargs["ExpiresIn"] == 900


def test_recorded_prefix_pagination_and_empty_outputs():
    prefix = "users/original-owner/jobs/task-1/outputs/"
    handler, _, s3 = admin_api({"artifact_prefix": prefix.removesuffix("outputs/")}, pages=[
        {"Contents": [{"Key": prefix, "Size": 0}], "NextContinuationToken": "page-2"},
        {"Contents": [{"Key": prefix + "panel.zip", "Size": 100}]},
    ])
    assert handler({}, "task-1")[1]["outputs"][0]["name"] == "panel.zip"
    assert s3.list_objects_v2.call_args.kwargs == {
        "Bucket": "private-artifacts", "Prefix": prefix, "ContinuationToken": "page-2",
    }
    assert s3.generate_presigned_url.call_count == 1
    handler, _, s3 = admin_api({"guest": True})
    assert handler({}, "task-1")[1]["outputs"] == []
    s3.generate_presigned_url.assert_not_called()

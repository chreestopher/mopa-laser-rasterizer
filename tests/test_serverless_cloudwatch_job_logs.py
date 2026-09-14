from pathlib import Path

from job_runtime import DynamoJobRuntime


ROOT = Path(__file__).resolve().parents[1]


class RecordingTable:
    def __init__(self):
        self.updates = []
        self.puts = []

    def update_item(self, **kwargs):
        self.updates.append(kwargs)
        return {}

    def put_item(self, **kwargs):
        self.puts.append(kwargs)
        return {}


def runtime_with_table():
    runtime = DynamoJobRuntime.__new__(DynamoJobRuntime)
    runtime.table = RecordingTable()
    runtime.ttl = 604800
    return runtime


def test_dynamo_runtime_logs_only_to_stdout(capsys):
    runtime = runtime_with_table()

    runtime.append_log("job-123", "processed another ribbon")

    assert capsys.readouterr().out == "[Task job-123] processed another ribbon\n"
    assert runtime.table.updates == []
    assert runtime.table.puts == []


def test_worker_registers_one_cloudwatch_stream_reference():
    runtime = runtime_with_table()

    runtime.set_cloudwatch_log_stream(
        "job-123", "/ecs/staging-worker", "worker/raster-worker/ecs-task-id"
    )

    assert len(runtime.table.updates) == 1
    values = runtime.table.updates[0]["ExpressionAttributeValues"]
    assert values[":log_group"] == "/ecs/staging-worker"
    assert values[":log_stream"] == "worker/raster-worker/ecs-task-id"
    assert runtime.table.puts == []


def test_serverless_api_reads_cloudwatch_with_dynamodb_fallback():
    handler = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")
    worker = (ROOT / "worker.py").read_text(encoding="utf-8")
    web_stack = (ROOT / "ecs" / "serverless-staging-web.yaml").read_text(encoding="utf-8")
    worker_stack = (ROOT / "ecs" / "rasterizer-worker.yaml").read_text(encoding="utf-8")

    assert "cloudwatch_logs.get_log_events" in handler
    assert 'Key("sk").begins_with("LOG#")' in handler
    assert "register_cloudwatch_log_stream(runtime, task_id)" in worker
    assert "Action: logs:GetLogEvents" in web_stack
    assert "WORKER_LOG_GROUP_NAME: !Ref WorkerLogGroupName" in web_stack
    assert "Name: CLOUDWATCH_LOG_GROUP, Value: !Ref LogGroup" in worker_stack
    assert "Default: 7" in worker_stack

"""Pluggable runtime state for raster jobs.

Production remains Redis-backed unless JOB_BACKEND=aws is explicitly selected.
The AWS backend keeps task payload, status, logs, ownership, and worker lease in
one DynamoDB item so one-shot Fargate workers no longer need network access to
the K3s Redis service.
"""

import json
import os
import time
from abc import ABC, abstractmethod
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError


def _dynamo_value(value):
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {key: _dynamo_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_dynamo_value(item) for item in value]
    return value


def _plain_value(value):
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    if isinstance(value, dict):
        return {key: _plain_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain_value(item) for item in value]
    return value


class JobRuntime(ABC):
    @abstractmethod
    def create(self, task_id, status="pending", logs=None): ...

    @abstractmethod
    def status(self, task_id): ...

    @abstractmethod
    def set_status(self, task_id, status, error=None): ...

    @abstractmethod
    def append_log(self, task_id, message): ...

    @abstractmethod
    def logs(self, task_id, after=0): ...

    @abstractmethod
    def put_payload(self, task_id, payload): ...

    @abstractmethod
    def payload(self, task_id): ...

    @abstractmethod
    def bind_access(self, task_id, kind, value): ...

    @abstractmethod
    def access(self, task_id): ...

    @abstractmethod
    def acquire_lease(self, task_id, owner, seconds): ...

    @abstractmethod
    def refresh_lease(self, task_id, owner, seconds): ...

    @abstractmethod
    def release_lease(self, task_id, owner): ...

    def claim_guest_quota(self, task_id, visitor, day, limit):
        """Atomically consume one validated guest run; non-AWS runtimes have no quota."""
        return True


class RedisJobRuntime(JobRuntime):
    def __init__(self, client, ttl_seconds, payload_prefix):
        self.client = client
        self.ttl = ttl_seconds
        self.payload_prefix = payload_prefix

    def create(self, task_id, status="pending", logs=None):
        pipe = self.client.pipeline()
        pipe.set(f"task:{task_id}:status", status, ex=self.ttl)
        for message in logs or []:
            pipe.rpush(f"task:{task_id}:log", message)
        pipe.expire(f"task:{task_id}:log", self.ttl)
        pipe.execute()

    def status(self, task_id):
        return self.client.get(f"task:{task_id}:status")

    def set_status(self, task_id, status, error=None):
        self.client.set(f"task:{task_id}:status", status, ex=self.ttl)
        if error:
            self.append_log(task_id, error)

    def append_log(self, task_id, message):
        print(f"[Task {task_id}] {message}", flush=True)
        pipe = self.client.pipeline()
        pipe.rpush(f"task:{task_id}:log", str(message))
        pipe.expire(f"task:{task_id}:log", self.ttl)
        pipe.execute()

    def logs(self, task_id, after=0):
        key = f"task:{task_id}:log"
        count = self.client.llen(key)
        return (self.client.lrange(key, after, -1) if count > after else []), count

    def put_payload(self, task_id, payload):
        raw = json.dumps(payload, separators=(",", ":"))
        self.client.set(f"{self.payload_prefix}{task_id}", raw, ex=self.ttl)
        return raw

    def payload(self, task_id):
        raw = self.client.get(f"{self.payload_prefix}{task_id}")
        return json.loads(raw) if raw else None

    def bind_access(self, task_id, kind, value):
        self.client.set(f"task:{task_id}:access", json.dumps({"kind": kind, "value": value}), ex=self.ttl)

    def access(self, task_id):
        raw = self.client.get(f"task:{task_id}:access")
        return json.loads(raw) if raw else None

    def acquire_lease(self, task_id, owner, seconds):
        return bool(self.client.set(f"rasterizer:job:{task_id}:lease", owner, nx=True, ex=seconds))

    def refresh_lease(self, task_id, owner, seconds):
        key = f"rasterizer:job:{task_id}:lease"
        if self.client.get(key) != owner:
            return False
        return bool(self.client.expire(key, seconds))

    def release_lease(self, task_id, owner):
        key = f"rasterizer:job:{task_id}:lease"
        if self.client.get(key) == owner:
            self.client.delete(key)
            return True
        return False


class DynamoJobRuntime(JobRuntime):
    def __init__(self, table_name, region, ttl_seconds):
        if not table_name:
            raise RuntimeError("JOB_RUNTIME_TABLE_NAME or DYNAMODB_TABLE_NAME is required for JOB_BACKEND=aws")
        self.table = boto3.resource("dynamodb", region_name=region).Table(table_name)
        self.ttl = ttl_seconds

    @staticmethod
    def _key(task_id):
        return {"pk": f"JOB#{task_id}", "sk": "RUNTIME"}

    def _expiry(self):
        return int(time.time()) + self.ttl

    def create(self, task_id, status="pending", logs=None):
        now = int(time.time())
        self.table.put_item(Item={**self._key(task_id), "task_id": task_id, "status": status,
                                  "log_count": 0, "created_at": now,
                                  "updated_at": now, "expires_at": self._expiry()},
                            ConditionExpression="attribute_not_exists(pk)")
        for message in logs or []:
            self.append_log(task_id, message)

    def _item(self, task_id, consistent=False):
        return self.table.get_item(Key=self._key(task_id), ConsistentRead=consistent).get("Item")

    def status(self, task_id):
        item = self._item(task_id)
        return item.get("status") if item else None

    def set_status(self, task_id, status, error=None):
        names = {"#status": "status"}
        values = {":status": status, ":now": int(time.time()), ":expiry": self._expiry()}
        expression = "SET #status=:status, updated_at=:now, expires_at=:expiry"
        if error:
            values[":error"] = str(error)[:2000]
            expression += ", error_message=:error"
        self.table.update_item(Key=self._key(task_id), UpdateExpression=expression,
                               ExpressionAttributeNames=names, ExpressionAttributeValues=values)

    def append_log(self, task_id, message):
        """Emit detailed AWS job output through the task's CloudWatch stream.

        The ECS awslogs driver already persists stdout. Avoid duplicating every
        processing line as two DynamoDB writes (an atomic counter update plus a
        separate LOG item); DynamoDB remains the authoritative status store.
        """
        print(f"[Task {task_id}] {message}", flush=True)

    def set_cloudwatch_log_stream(self, task_id, log_group, log_stream):
        """Bind a one-shot ECS worker's deterministic log stream to its job."""
        if not log_group or not log_stream:
            return
        self.table.update_item(
            Key=self._key(task_id),
            UpdateExpression=(
                "SET cloudwatch_log_group=:log_group, "
                "cloudwatch_log_stream=:log_stream, updated_at=:now, expires_at=:expiry"
            ),
            ExpressionAttributeValues={
                ":log_group": str(log_group), ":log_stream": str(log_stream),
                ":now": int(time.time()), ":expiry": self._expiry(),
            },
        )

    def claim_guest_quota(self, task_id, visitor, day, limit):
        """Count each validated task once, including safe retries of the same task."""
        if not visitor or not day or int(limit) < 1:
            return False
        try:
            self.table.update_item(
                Key={"pk": f"GUESTQUOTA#{visitor}", "sk": f"DAY#{day}"},
                UpdateExpression="SET expires_at=:expiry ADD claimed_tasks :tasks",
                ConditionExpression=(
                    "attribute_not_exists(claimed_tasks) OR "
                    "contains(claimed_tasks,:task) OR size(claimed_tasks) < :limit"
                ),
                ExpressionAttributeValues={
                    ":expiry": int(time.time()) + 2 * 86400,
                    ":tasks": {str(task_id)}, ":task": str(task_id),
                    ":limit": int(limit),
                },
            )
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False
            raise
        return True

    def logs(self, task_id, after=0):
        item = self._item(task_id) or {}
        count = int(item.get("log_count") or 0)
        after = max(0, int(after))
        if count <= after:
            return [], count
        response = self.table.query(
            KeyConditionExpression=(
                Key("pk").eq(self._key(task_id)["pk"])
                & Key("sk").between(f"LOG#{after + 1:09d}", "LOG#~")
            ),
            ScanIndexForward=True,
        )
        return [str(item.get("message", "")) for item in response.get("Items", [])], count

    def put_payload(self, task_id, payload):
        self.table.update_item(
            Key=self._key(task_id),
            UpdateExpression="SET payload=:payload, updated_at=:now, expires_at=:expiry",
            ExpressionAttributeValues={":payload": _dynamo_value(payload),
                                       ":now": int(time.time()), ":expiry": self._expiry()},
        )
        return json.dumps(payload, separators=(",", ":"))

    def payload(self, task_id):
        item = self._item(task_id, consistent=True) or {}
        return _plain_value(item.get("payload"))

    def bind_access(self, task_id, kind, value):
        self.table.update_item(
            Key=self._key(task_id),
            UpdateExpression="SET access_kind=:kind, access_value=:value, expires_at=:expiry",
            ExpressionAttributeValues={":kind": kind, ":value": value, ":expiry": self._expiry()},
        )

    def access(self, task_id):
        item = self._item(task_id) or {}
        if item.get("access_kind") and item.get("access_value"):
            return {"kind": item["access_kind"], "value": item["access_value"]}
        return None

    def acquire_lease(self, task_id, owner, seconds):
        now = int(time.time())
        try:
            self.table.update_item(
                Key=self._key(task_id),
                UpdateExpression="SET lease_owner=:owner, lease_expires_at=:lease_expiry, updated_at=:now",
                ConditionExpression="attribute_exists(pk) AND (attribute_not_exists(lease_expires_at) OR lease_expires_at < :now)",
                ExpressionAttributeValues={":owner": owner, ":lease_expiry": now + seconds, ":now": now},
            )
            return True
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False
            raise

    def refresh_lease(self, task_id, owner, seconds):
        now = int(time.time())
        try:
            self.table.update_item(
                Key=self._key(task_id),
                UpdateExpression="SET lease_expires_at=:expiry, updated_at=:now",
                ConditionExpression="lease_owner=:owner AND lease_expires_at >= :now",
                ExpressionAttributeValues={":owner": owner, ":expiry": now + seconds, ":now": now},
            )
            return True
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False
            raise

    def release_lease(self, task_id, owner):
        try:
            self.table.update_item(Key=self._key(task_id),
                                   UpdateExpression="REMOVE lease_owner, lease_expires_at",
                                   ConditionExpression="lease_owner=:owner",
                                   ExpressionAttributeValues={":owner": owner})
            return True
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False
            raise


def create_job_runtime(redis_client, ttl_seconds, payload_prefix):
    backend = os.environ.get("JOB_BACKEND", "redis").strip().lower()
    if backend == "redis":
        return RedisJobRuntime(redis_client, ttl_seconds, payload_prefix)
    if backend == "aws":
        return DynamoJobRuntime(
            os.environ.get("JOB_RUNTIME_TABLE_NAME", os.environ.get("DYNAMODB_TABLE_NAME", "")).strip(),
            os.environ.get("AWS_REGION", "us-east-2").strip(), ttl_seconds,
        )
    raise RuntimeError("JOB_BACKEND must be either 'redis' or 'aws'")

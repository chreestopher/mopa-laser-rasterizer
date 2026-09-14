import json
import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("AWS_CONFIG_FILE", "/dev/null")
os.environ.setdefault("AWS_SHARED_CREDENTIALS_FILE", "/dev/null")
os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")

import services
import worker


class WorkerTaskIdTests(unittest.TestCase):
    def test_enqueue_persists_addressable_payload_before_legacy_publish(self):
        redis_client = MagicMock()
        payload = {"task_id": "task-123", "image_key": "inputs/image.png"}

        with patch.object(services, "redis_client", redis_client), patch.object(
            services, "SQS_QUEUE_URL", ""
        ), patch.object(services, "FARGATE_DISPATCH_VIA_S3", False):
            raw_payload = services.store_and_enqueue_job(payload)

        pipeline = redis_client.pipeline.return_value
        pipeline.set.assert_called_once_with(
            f"{services.RASTER_JOB_PAYLOAD_PREFIX}task-123",
            raw_payload,
            ex=services.HISTORY_TTL_SECONDS,
        )
        pipeline.lpush.assert_called_once_with(services.RASTER_JOB_QUEUE, raw_payload)
        pipeline.execute.assert_called_once_with()

    def test_sqs_publish_uses_only_task_id_and_skips_legacy_queue(self):
        redis_client = MagicMock()
        sqs_client = MagicMock()
        payload = {"task_id": "task-456", "image_key": "inputs/image.png"}

        with patch.object(services, "redis_client", redis_client), patch.object(
            services, "sqs_client", sqs_client
        ), patch.object(services, "SQS_QUEUE_URL", "https://sqs.example/jobs"), patch.object(
            services, "FARGATE_DISPATCH_VIA_S3", False
        ):
            raw_payload = services.store_and_enqueue_job(payload)

        pipeline = redis_client.pipeline.return_value
        pipeline.set.assert_called_once_with(
            f"{services.RASTER_JOB_PAYLOAD_PREFIX}task-456",
            raw_payload,
            ex=services.HISTORY_TTL_SECONDS,
        )
        pipeline.lpush.assert_not_called()
        pipeline.execute.assert_called_once_with()
        sqs_client.send_message.assert_called_once_with(
            QueueUrl="https://sqs.example/jobs",
            MessageBody="task-456",
        )

    def test_s3_dispatch_marker_avoids_direct_sqs_network_dependency(self):
        redis_client = MagicMock()
        s3_client = MagicMock()
        payload = {"task_id": "task-789", "image_key": "inputs/image.png"}

        with patch.object(services, "redis_client", redis_client), patch.object(
            services, "s3_client", s3_client
        ), patch.object(services, "FARGATE_DISPATCH_VIA_S3", True):
            services.store_and_enqueue_job(payload)

        redis_client.pipeline.return_value.lpush.assert_not_called()
        s3_client.put_object.assert_called_once_with(
            Bucket=services.S3_BUCKET_NAME,
            Key="jobs/task-789/dispatch.ready",
            Body=b"",
            ContentType="application/x-mopa-raster-dispatch",
        )

    def test_one_shot_worker_claims_only_requested_payload(self):
        task_id = "task-123"
        raw_payload = json.dumps({"task_id": task_id})
        redis_client = MagicMock()
        redis_client.get.side_effect = lambda key: (
            raw_payload if key == f"{services.RASTER_JOB_PAYLOAD_PREFIX}{task_id}" else "pending"
        )
        redis_client.set.return_value = True

        with patch.object(worker, "redis_client", redis_client), patch.object(
            worker, "process_owned_job", return_value=True
        ) as process_owned_job:
            exit_code = worker.run_task_by_id(task_id, "/tmp/uploads")

        self.assertEqual(0, exit_code)
        process_owned_job.assert_called_once_with(raw_payload, task_id, "/tmp/uploads")
        pipeline = redis_client.pipeline.return_value
        pipeline.lrem.assert_any_call(services.RASTER_JOB_QUEUE, 0, raw_payload)
        pipeline.lrem.assert_any_call(services.RASTER_JOB_PROCESSING_QUEUE, 0, raw_payload)
        pipeline.rpush.assert_called_once_with(services.RASTER_JOB_PROCESSING_QUEUE, raw_payload)

    def test_completed_one_shot_delivery_is_idempotent(self):
        redis_client = MagicMock()
        redis_client.get.return_value = "completed"
        with patch.object(worker, "redis_client", redis_client), patch.object(
            worker, "process_owned_job"
        ) as process_owned_job:
            exit_code = worker.run_task_by_id("task-123", "/tmp/uploads")

        self.assertEqual(0, exit_code)
        process_owned_job.assert_not_called()
        redis_client.set.assert_not_called()


if __name__ == "__main__":
    unittest.main()

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class JobHistoryLiveLogCoverageTests(unittest.TestCase):
    def test_selected_running_job_logs_are_polled_incrementally(self):
        template = (ROOT / "templates" / "loading.html").read_text(encoding="utf-8")

        self.assertIn("async function pollSelectedTaskLogs()", template)
        self.assertIn("?after=${selectedLogIndex}", template)
        self.assertIn("if (activeLogTaskId !== selectedTaskId) return", template)
        self.assertIn("setInterval(pollSelectedTaskLogs, 1000)", template)
        self.assertIn("selectedLogTerminal = data.status === 'completed' || data.status === 'failed'", template)

    def test_pending_jobs_are_presented_as_workers_starting(self):
        template = (ROOT / "templates" / "loading.html").read_text(encoding="utf-8")

        self.assertIn("status === 'pending' ? 'starting worker'", template)
        self.assertIn('id="worker-starting-indicator"', template)
        self.assertIn('class="worker-starting-dots" aria-hidden="true"', template)
        self.assertIn("workerStartingIndicator.hidden = status !== 'pending'", template)
        self.assertIn("@keyframes worker-starting-dot", template)
        self.assertIn("prefers-reduced-motion: reduce", template)
        self.assertIn("Starting raster worker", template)

    def test_sqs_status_does_not_report_legacy_redis_queue_position(self):
        jobs = (ROOT / "routes" / "jobs.py").read_text(encoding="utf-8")
        holographic = (ROOT / "routes" / "holographic.py").read_text(encoding="utf-8")

        self.assertIn('os.environ.get("FARGATE_DISPATCH_VIA_S3", "")', jobs)
        self.assertIn('os.environ.get("FARGATE_DISPATCH_VIA_S3", "")', holographic)


if __name__ == "__main__":
    unittest.main()

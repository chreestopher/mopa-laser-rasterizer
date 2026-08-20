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


if __name__ == "__main__":
    unittest.main()

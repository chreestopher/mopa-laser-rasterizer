import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LogWrappingTests(unittest.TestCase):
    def test_serverless_live_status_wraps_unbroken_log_values(self):
        page = (ROOT / "serverless_web" / "index.html").read_text(encoding="utf-8")

        self.assertIn("overflow-wrap:anywhere", page)
        self.assertIn("word-break:break-word", page)
        self.assertIn("overflow-x:hidden", page)

    def test_serverless_retained_log_views_cannot_widen_the_viewport(self):
        history = (ROOT / "serverless_web" / "history.html").read_text(encoding="utf-8")
        admin = (ROOT / "serverless_web" / "admin.css").read_text(encoding="utf-8")

        for source in (history, admin):
            self.assertIn("overflow-wrap:anywhere", source)
            self.assertIn("word-break:break-word", source)
            self.assertIn("min-width:0", source)
            self.assertIn("max-width:100%", source)

    def test_legacy_live_terminal_wraps_and_treats_logs_as_text(self):
        page = (ROOT / "templates" / "loading.html").read_text(encoding="utf-8")

        self.assertIn("overflow-wrap: anywhere", page)
        self.assertIn("word-break: break-word", page)
        self.assertIn("li.append(prefix, document.createTextNode(cleanMessage))", page)
        self.assertNotIn('li.innerHTML = `<span class="log-prefix">$</span>${cleanMessage}`', page)


if __name__ == "__main__":
    unittest.main()

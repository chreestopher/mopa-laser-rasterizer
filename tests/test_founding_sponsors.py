import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FoundingSponsorsCoverageTests(unittest.TestCase):
    def test_founding_sponsors_page_is_routed_and_indexed_but_not_in_primary_nav(self):
        home = (ROOT / "routes" / "home.py").read_text(encoding="utf-8")
        docs = (ROOT / "routes" / "docs.py").read_text(encoding="utf-8")
        chrome = (ROOT / "templates" / "_machine_chrome.html").read_text(encoding="utf-8")
        page = (ROOT / "templates" / "founding_sponsors.html").read_text(encoding="utf-8")

        self.assertIn('@routes.route("/founding-sponsors")', home)
        self.assertIn('"founding_sponsors.html"', home)
        self.assertIn('"/founding-sponsors"', docs)
        self.assertNotIn('href="/founding-sponsors"', chrome)
        self.assertIn("Under construction - coming soon", page)
        self.assertIn("{% for sponsor in sponsors %}", page)
        self.assertIn('rel="sponsored noopener"', page)


if __name__ == "__main__":
    unittest.main()

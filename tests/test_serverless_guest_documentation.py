import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ServerlessGuestDocumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = (ROOT / "routes" / "docs.py").read_text(encoding="utf-8")
        cls.hub = (ROOT / "templates" / "docs.html").read_text(encoding="utf-8")
        cls.documentation = cls.catalog + "\n" + cls.hub

    def test_guest_rasterizer_quota_matches_staging(self):
        self.assertIn("five successfully validated jobs per UTC day", self.documentation)
        self.assertIn("bad inputs rejected during that validation do not consume", self.catalog)
        self.assertNotIn("three accepted jobs", self.documentation)
        self.assertNotIn("three free Rasterizer jobs", self.documentation)

    def test_guest_jobs_are_not_described_as_account_history(self):
        self.assertIn("guest jobs are not added to Job History", self.catalog)
        self.assertIn("signed download links shown when completion is observed expire after 15 minutes", self.catalog)
        self.assertNotIn("Guest history is tied to the browser session", self.documentation)
        self.assertNotIn("upload a LightBurn Material Library for the current browser session", self.hub)

    def test_guest_laboratory_boundaries_are_documented(self):
        self.assertIn("They can export enabled, qualified swatches as a .clb file", self.catalog)
        self.assertIn("Guests can download the self-contained Holographic Swatch Palette file", self.catalog)
        self.assertIn("a guest can upload it on the Rasterizer page to run Holographic Artwork", self.catalog)
        self.assertIn("use it to generate Holographic Artwork", self.hub)
        self.assertNotIn("or Holographic Artwork processing", self.hub)
        self.assertIn("saved Depth Palette color guidance requires signing in", self.catalog)

    def test_member_only_resources_are_identified(self):
        self.assertIn("Browsing and searching Community Set is available to signed-in members", self.catalog)
        self.assertIn("personal Swatch Palette Vault and Community Set", self.catalog)
        self.assertIn("Signed-in members can choose a Holographic Palette saved in Swatch Palette Vault", self.catalog)
        self.assertIn("Guests can choose Upload Holographic Swatch Palette", self.catalog)


if __name__ == "__main__":
    unittest.main()

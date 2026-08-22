import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DepthMapGeneratorCoverageTests(unittest.TestCase):
    def test_unlisted_depthmap_page_uses_client_side_inference(self):
        home = (ROOT / "routes" / "home.py").read_text(encoding="utf-8")
        docs = (ROOT / "routes" / "docs.py").read_text(encoding="utf-8")
        chrome = (ROOT / "templates" / "_machine_chrome.html").read_text(encoding="utf-8")
        page = (ROOT / "templates" / "depthmap_generator.html").read_text(encoding="utf-8")
        script = (ROOT / "static" / "depthmap_generator.js").read_text(encoding="utf-8")

        self.assertIn('@routes.route("/depthmap-generator")', home)
        self.assertIn('"depthmap_generator.html"', home)
        self.assertNotIn('"/depthmap-generator"', docs)
        self.assertNotIn('href="/depthmap-generator"', chrome)
        self.assertIn('content="noindex,nofollow"', page)
        self.assertIn('src="/static/depthmap_generator.js?v=1"', page)
        self.assertIn('pipeline("depth-estimation"', script)
        self.assertIn('options.device = "webgpu"', script)
        self.assertIn('CompressionStream("deflate")', script)
        self.assertIn('Download 16-bit PNG', page)
        self.assertIn('id="depth_output_width"', page)
        self.assertIn('id="depth_output_height"', page)
        self.assertIn("#depth_input::file-selector-button", page)
        self.assertIn("#depth_input::-webkit-file-upload-button", page)
        self.assertIn('id="depth_brush_size"', page)
        self.assertIn('id="depth_clear_paint"', page)
        self.assertIn("outputDepth.fill(farthest)", script)
        self.assertIn('mapCanvas.addEventListener("pointerdown"', script)
        self.assertIn("farPaintMask[index] = 1", script)
        self.assertIn("const farthest = invertControl.checked ? 1 : 0", script)
        self.assertIn("Math.min(outputWidth / depthWidth, outputHeight / depthHeight)", script)
        self.assertEqual(script.count("createImageData(outputWidth, outputHeight)"), 2)
        self.assertNotIn("createImageData(depthWidth, depthHeight)", script)


if __name__ == "__main__":
    unittest.main()

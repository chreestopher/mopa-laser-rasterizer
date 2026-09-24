import ast
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RecentFeatureDocumentationTests(unittest.TestCase):
    def test_recent_workflow_guides_render_and_are_linked(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "docs"
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "dev_setup" / "build_serverless_docs.py"),
                    str(output),
                    "https://staging.example.com",
                ],
                check=True,
            )

            index = (output / "index.html").read_text(encoding="utf-8")
            cropping = (output / "artwork-cropping").read_text(encoding="utf-8")
            geometry = (output / "geometry-styles").read_text(encoding="utf-8")
            halftone = (output / "halftone-newsprint-geometry").read_text(encoding="utf-8")
            krasnow = (output / "krasnow-grating-geometry").read_text(encoding="utf-8")
            export = (output / "lightburn-export").read_text(encoding="utf-8")
            color_layers = (output / "color-layers").read_text(encoding="utf-8")

            self.assertIn('href="/docs/artwork-cropping"', index)
            self.assertIn('href="/docs/geometry-styles"', index)
            self.assertIn('href="/docs/halftone-newsprint-geometry"', index)
            self.assertIn('href="/docs/krasnow-grating-geometry"', index)
            self.assertIn("Crop transparency", cropping)
            self.assertIn("transparent holes inside it remain transparent", cropping)
            self.assertIn("Choose by swatch", geometry)
            self.assertIn("mutually exclusive", geometry)
            self.assertIn("Invert Fill", geometry)
            self.assertIn("paw print", geometry)
            self.assertIn("Fauxlogram Gradient Scope", geometry)
            self.assertIn("vertically, horizontally, or radially", geometry)
            self.assertIn("Dot Size Source", halftone)
            self.assertIn("<h1>Halftone Newsprint Geometry Style</h1>", halftone)
            self.assertFalse((output / "glyph-mosaic-filter").exists())
            self.assertFalse((output / "halftone-newsprint-filter").exists())
            self.assertFalse((output / "krasnow-grating-filter").exists())
            self.assertIn("Preserve Black disabled", krasnow)
            self.assertIn("uses the Fauxlographic setting as the authoritative template", krasnow)
            self.assertIn("Additional sublayers, if present, are ignored", krasnow)
            self.assertIn("Fauxlogram Gradient controls in Geometry Style", krasnow)
            self.assertIn("whole-artwork radial layouts", krasnow)
            self.assertIn("50,000,000 bytes", export)
            self.assertIn("Geometry Style and its parameters", export)
            self.assertNotIn("synthetic full-canvas shape", color_layers)
            self.assertIn("If the selected material has no setting assigned to Black", color_layers)
            self.assertIn("omits the synthetic Black canvas", color_layers)

            handler_tree = ast.parse(
                (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")
            )
            palette = next(
                ast.literal_eval(node.value)
                for node in handler_tree.body
                if isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id == "PALETTE"
                    for target in node.targets
                )
            )
            self.assertEqual(len(palette), 30)
            positions = []
            for index, (name, color) in enumerate(palette):
                row = f"<td><code>C{index:02d}</code></td><td>{name}</td>"
                self.assertIn(row, color_layers)
                self.assertIn(f"background-color:{color}", color_layers)
                positions.append(color_layers.index(row))
            self.assertEqual(positions, sorted(positions))


if __name__ == "__main__":
    unittest.main()

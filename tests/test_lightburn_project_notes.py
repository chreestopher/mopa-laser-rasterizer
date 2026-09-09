import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from lightburn import Lightburn
import vector_processing


class LightBurnProjectNotesTests(unittest.TestCase):
    def test_notes_are_serialized_with_show_on_load_and_line_breaks(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "notes.lbrn2"
            project = Lightburn()
            project.set_notes('First line\nSecond "line" & detail', show_on_load=True)
            project.write(output)

            notes = ET.parse(output).getroot().find("Notes")
            self.assertIsNotNone(notes)
            self.assertEqual(notes.attrib["ShowOnLoad"], "1")
            self.assertEqual(notes.attrib["Notes"], 'First line\nSecond "line" & detail')

    def test_large_file_warning_can_replace_only_the_notes_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "notes.lbrn2"
            project = Lightburn()
            project.set_notes("Rasterizer Parameters\nJob type: Rasterizer")
            project.write(output)
            project.replace_notes_tail(
                output,
                "WARNING: Large project\n\nRasterizer Parameters\nJob type: Rasterizer",
            )

            root = ET.parse(output).getroot()
            notes = root.findall("Notes")
            self.assertEqual(len(notes), 1)
            self.assertTrue(notes[0].attrib["Notes"].startswith("WARNING: Large project\n\n"))

    def test_rasterizer_export_adds_parameters_and_conditional_large_file_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "project.vector.svg"
            project = Lightburn()
            note = vector_processing.build_rasterizer_project_note(
                image_preset="abstract",
                width=800,
                height=600,
                scale_factor=0.0625,
                quantize_colors=3,
                min_island_area=2,
                simplification_factor=0.1,
                smoothing_radius=0.001,
                abstract_filter="krasnow_grating",
                abstract_filter_parameters={"preserve_black": True, "_private": object()},
                color_matching={"color_matching_mode": "balanced"},
                job_settings={"selected_material": "Stainless Steel"},
                target_colors={
                    "#000000": (0, 0, "black"),
                    "#3366FF": (0, 1, "blue"),
                },
                geometry_style="glyphs",
                geometry_style_parameters={"glyph_shape": "star", "_private": object()},
            )
            with patch.object(vector_processing, "LARGE_LIGHTBURN_PROJECT_BYTES", 1):
                vector_processing.save_vector_output(
                    root=ET.Element("svg"),
                    output_svg_path=str(output),
                    lb_project_instance=project,
                    lightburn_note=note,
                )

            saved_note = ET.parse(f"{output}.lbrn2").getroot().find("Notes").attrib["Notes"]
            self.assertTrue(saved_note.startswith(vector_processing.LARGE_LIGHTBURN_PROJECT_WARNING))
            self.assertIn("Job type: Rasterizer", saved_note)
            self.assertIn("Abstract filter: Krasnow Grating", saved_note)
            self.assertIn("- Preserve Black: On", saved_note)
            self.assertIn("Geometry style: Glyphs", saved_note)
            self.assertIn("- Glyph Shape: star", saved_note)
            self.assertNotIn("private", saved_note.casefold())

    def test_holographic_artwork_is_labeled_as_holographic(self):
        note = vector_processing.build_rasterizer_project_note(
            image_preset="holographic_artwork",
            width=100,
            height=100,
            scale_factor=0.1,
            quantize_colors=2,
            min_island_area=0,
            simplification_factor=0,
            smoothing_radius=0,
            abstract_filter="none",
            abstract_filter_parameters={},
            color_matching={},
            job_settings={},
            target_colors={},
        )
        self.assertIn("Job type: Holographic", note)


if __name__ == "__main__":
    unittest.main()

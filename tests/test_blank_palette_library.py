import unittest
from xml.etree import ElementTree as ET

from lib.material_library_template import (
    DEFAULT_RASTERIZER_PALETTE,
    build_blank_palette_library,
)


class BlankPaletteLibraryTests(unittest.TestCase):
    def test_template_contains_one_safe_placeholder_per_default_swatch(self):
        library = build_blank_palette_library("colors - stainless steel")
        root = ET.parse(library).getroot()
        material = root.find("Material")
        entries = material.findall("Entry")

        self.assertEqual("colors - stainless steel", material.attrib["name"])
        self.assertEqual(30, len(entries))
        self.assertEqual(
            [f"UNCONFIGURED {name}" for name, _index in DEFAULT_RASTERIZER_PALETTE],
            [entry.attrib["Desc"] for entry in entries],
        )
        for entry in entries:
            self.assertEqual("-1.0000", entry.attrib["Thickness"])
            self.assertNotIn("NoThickTitle", entry.attrib)
            cut = entry.find("CutSetting")
            values = {child.tag: child.attrib.get("Value") for child in cut}
            self.assertEqual("0", values["index"])
            self.assertEqual("", values["name"])
            self.assertEqual("0", values["maxPower"])
            self.assertEqual("0", values["speed"])
            self.assertEqual("0", values["doOutput"])
            self.assertEqual("1", values["hide"])
            self.assertNotIn("RasterizerPlaceholder", values)

    def test_material_name_is_required_and_bounded(self):
        for invalid_name in ("", "   ", "x" * 161, "bad\nname"):
            with self.subTest(invalid_name=invalid_name):
                with self.assertRaises(ValueError):
                    build_blank_palette_library(invalid_name)


if __name__ == "__main__":
    unittest.main()

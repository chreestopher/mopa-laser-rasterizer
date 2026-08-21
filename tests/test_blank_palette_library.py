import unittest
from xml.etree import ElementTree as ET

from lib.material_library_template import (
    DEFAULT_RASTERIZER_PALETTE,
    build_blank_palette_library,
    build_hatch_palette_library,
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

    def test_hatch_palette_clones_base_setting_and_only_varies_hatch_fields(self):
        base_entry = ET.fromstring("""
          <Entry Thickness="-1.0000" Desc="Base"><CutSetting type="Offset" custom="keep">
            <index Value="9"/><name Value="Base"/><speed Value="400"/>
            <maxPower Value="30"/><frequency Value="300000"/><interval Value="0.2"/><angle Value="-90"/>
            <customField Value="preserved"/>
            <SubLayer type="Offset"><speed Value="350"/><interval Value="0.3"/><angle Value="12"/></SubLayer>
          </CutSetting></Entry>
        """)

        root = ET.parse(build_hatch_palette_library(
            "steel hatches", interval_mm=0.1, base_entry=base_entry
        )).getroot()
        entries = root.findall("Material/Entry")

        self.assertEqual(30, len(entries))
        self.assertEqual([name for name, _index in DEFAULT_RASTERIZER_PALETTE], [entry.attrib["Desc"] for entry in entries])
        for entry in entries:
            cut = entry.find("CutSetting")
            self.assertEqual("Offset", cut.attrib["type"])
            self.assertEqual("400", cut.find("speed").attrib["Value"])
            self.assertEqual("30", cut.find("maxPower").attrib["Value"])
            self.assertEqual("preserved", cut.find("customField").attrib["Value"])
            self.assertEqual("350", cut.find("SubLayer/speed").attrib["Value"])
            self.assertEqual("0.1", cut.find("interval").attrib["Value"])
            self.assertEqual("0.1", cut.find("SubLayer/interval").attrib["Value"])
            self.assertEqual(cut.find("angle").attrib["Value"], cut.find("SubLayer/angle").attrib["Value"])

        by_description = {entry.attrib["Desc"]: entry for entry in entries}
        self.assertEqual("0", by_description["Black"].find("CutSetting/angle").attrib["Value"])
        self.assertEqual("162", by_description["Teal"].find("CutSetting/angle").attrib["Value"])


if __name__ == "__main__":
    unittest.main()

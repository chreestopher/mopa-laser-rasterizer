import unittest
from xml.etree import ElementTree as ET

from routes.account import (
    apply_entry_update,
    apply_hatch_plan,
    material_coupon_project,
    validate_unique_entry_descriptions,
)


class MaterialCouponTests(unittest.TestCase):
    def test_duplicate_swatch_names_are_rejected_within_one_material(self):
        library = ET.fromstring("""
            <LightBurnLibrary><Material name="steel">
              <Entry Desc="Dark-Orange"><CutSetting type="Scan"/></Entry>
              <Entry Desc=" dark-orange "><CutSetting type="Scan"/></Entry>
            </Material></LightBurnLibrary>
        """)

        with self.assertRaisesRegex(ValueError, "duplicate swatch name.*Dark-Orange"):
            validate_unique_entry_descriptions(library)

    def test_same_swatch_name_is_allowed_in_different_materials(self):
        library = ET.fromstring("""
            <LightBurnLibrary>
              <Material name="steel"><Entry Desc="Blue"><CutSetting type="Scan"/></Entry></Material>
              <Material name="aluminum"><Entry Desc="blue"><CutSetting type="Scan"/></Entry></Material>
            </LightBurnLibrary>
        """)

        validate_unique_entry_descriptions(library)

    def test_coupon_allows_duplicate_names_from_multiple_libraries(self):
        library = ET.fromstring("""
            <LightBurnLibrary><Material name="combined coupon">
              <Entry Desc="Blue"><CutSetting type="Scan"><speed Value="500"/></CutSetting></Entry>
              <Entry Desc="Blue"><CutSetting type="Scan"><speed Value="900"/></CutSetting></Entry>
            </Material></LightBurnLibrary>
        """)

        project = material_coupon_project(library)

        self.assertEqual(["Blue", "Blue"], [
            layer.find("name").attrib["Value"] for layer in project.findall("CutSetting")[1:]
        ])

    def test_hatch_plan_preserves_base_settings_and_offset_mode(self):
        library = ET.fromstring("""
            <LightBurnLibrary><Material name="steel">
              <Entry Desc="Black"><CutSetting type="Offset"><speed Value="500"/><frequency Value="300000"/><interval Value="0.2"/><angle Value="90"/><SubLayer type="Offset"><speed Value="450"/><interval Value="0.3"/><angle Value="45"/></SubLayer></CutSetting></Entry>
              <Entry Desc="Blue"><CutSetting type="Scan"><speed Value="500"/><frequency Value="300000"/><interval Value="0.2"/><angle Value="90"/></CutSetting></Entry>
            </Material></LightBurnLibrary>
        """)

        apply_hatch_plan(library, start_angle=0, angle_span=180, interval_start=.1, interval_end=.2)

        black, blue = library.findall("Material/Entry")
        self.assertEqual("Offset", black.find("CutSetting").attrib["type"])
        self.assertEqual("Scan", blue.find("CutSetting").attrib["type"])
        self.assertEqual("500", black.find("CutSetting/speed").attrib["Value"])
        self.assertEqual("450", black.find("CutSetting/SubLayer/speed").attrib["Value"])
        self.assertEqual("0", black.find("CutSetting/angle").attrib["Value"])
        self.assertEqual("0", black.find("CutSetting/SubLayer/angle").attrib["Value"])
        self.assertEqual("90", blue.find("CutSetting/angle").attrib["Value"])
        self.assertEqual("0.1", black.find("CutSetting/interval").attrib["Value"])
        self.assertEqual("0.2", blue.find("CutSetting/interval").attrib["Value"])

    def test_inline_setting_update_preserves_unsubmitted_lightburn_fields(self):
        library = ET.fromstring("""
            <LightBurnLibrary><Material name="steel">
              <Entry Desc="Blue"><CutSetting type="Scan" custom="keep-attribute">
                <index Value="7"/><name Value="original"/><speed Value="500"/>
                <customImportedValue Value="keep-value" custom="keep-field-attribute"/>
                <SubLayer type="Scan"><speed Value="250"/></SubLayer>
              </CutSetting></Entry>
            </Material></LightBurnLibrary>
        """)

        apply_entry_update(library, 0, {
            "material": "steel", "description": "Blue edited", "type": "Scan",
            "settings": {"speed": 750},
        })

        entry = library.find("Material/Entry")
        cut = entry.find("CutSetting")
        self.assertEqual("Blue edited", entry.attrib["Desc"])
        self.assertEqual("750", cut.find("speed").attrib["Value"])
        self.assertEqual("keep-attribute", cut.attrib["custom"])
        self.assertEqual("keep-value", cut.find("customImportedValue").attrib["Value"])
        self.assertEqual("keep-field-attribute", cut.find("customImportedValue").attrib["custom"])
        self.assertEqual("250", cut.find("SubLayer/speed").attrib["Value"])

    def test_each_selected_entry_becomes_one_layer_and_cell(self):
        library = ET.fromstring("""
            <LightBurnLibrary><Material name="steel">
              <Entry Desc="Red"><CutSetting type="Scan"><index Value="7"/><name Value="old"/><speed Value="500"/><maxPower Value="25"/></CutSetting></Entry>
              <Entry Desc="Blue"><CutSetting type="Cut"><index Value="7"/><name Value="old"/><speed Value="900"/><maxPower Value="40"/></CutSetting></Entry>
            </Material></LightBurnLibrary>
        """)

        project = material_coupon_project(library)
        layers = project.findall("CutSetting")
        cells = [shape for shape in project.findall("Shape[@Type='Rect']") if shape.attrib["CutIndex"] != "0"]

        self.assertEqual(["0", "1", "2"], [layer.find("index").attrib["Value"] for layer in layers])
        self.assertEqual(["Coupon labels", "Red", "Blue"], [layer.find("name").attrib["Value"] for layer in layers])
        self.assertEqual(["500", "500", "900"], [layer.find("speed").attrib["Value"] for layer in layers])
        self.assertEqual(["1", "2"], [cell.attrib["CutIndex"] for cell in cells])
        self.assertTrue(all(cell.attrib["W"] == "10" and cell.attrib["H"] == "10" for cell in cells))

        text = project.findall("Shape[@Type='Text']")
        self.assertEqual(["0", "0", "0"], [item.attrib["CutIndex"] for item in text])
        self.assertEqual(["Material Library Settings", "Red", "Blue"], [item.attrib["Str"] for item in text])
        self.assertIsNone(project.find("Shape[@Type='Rect'][@CutIndex='0']"))

    def test_coupon_scales_complete_layout_to_requested_dimensions(self):
        library = ET.fromstring("""
            <LightBurnLibrary><Material name="steel">
              <Entry Desc="Black"><CutSetting type="Scan"><index Value="0"/><name Value="Black"/></CutSetting></Entry>
            </Material></LightBurnLibrary>
        """)
        project = material_coupon_project(library, coupon_width_mm=50, coupon_length_mm=25)
        cell = next(shape for shape in project.findall("Shape[@Type='Rect']") if shape.attrib["CutIndex"] != "0")
        values = [float(value) for value in cell.find("XForm").text.split()]
        self.assertAlmostEqual(5.0, values[0])
        self.assertAlmostEqual(25.0 / 21.0, values[3])

    def test_coupon_rejects_invalid_dimensions(self):
        library = ET.fromstring("""
            <LightBurnLibrary><Material name="steel">
              <Entry Desc="Black"><CutSetting type="Scan"/></Entry>
            </Material></LightBurnLibrary>
        """)
        with self.assertRaisesRegex(ValueError, "between 10 and 1000"):
            material_coupon_project(library, coupon_width_mm=5, coupon_length_mm=100)

    def test_coupon_rejects_more_than_thirty_layers(self):
        library = ET.Element("LightBurnLibrary")
        material = ET.SubElement(library, "Material", {"name": "steel"})
        for index in range(30):
            entry = ET.SubElement(material, "Entry", {"Desc": str(index)})
            ET.SubElement(entry, "CutSetting", {"type": "Scan"})
        with self.assertRaisesRegex(ValueError, "no more than 29"):
            material_coupon_project(library)


if __name__ == "__main__":
    unittest.main()

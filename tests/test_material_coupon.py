import unittest
from xml.etree import ElementTree as ET

from routes.account import material_coupon_project


class MaterialCouponTests(unittest.TestCase):
    def test_each_selected_entry_becomes_one_layer_and_cell(self):
        library = ET.fromstring("""
            <LightBurnLibrary><Material name="steel">
              <Entry Desc="Red"><CutSetting type="Scan"><index Value="7"/><name Value="old"/><speed Value="500"/><maxPower Value="25"/></CutSetting></Entry>
              <Entry Desc="Blue"><CutSetting type="Cut"><index Value="7"/><name Value="old"/><speed Value="900"/><maxPower Value="40"/></CutSetting></Entry>
            </Material></LightBurnLibrary>
        """)

        project = material_coupon_project(library)
        layers = project.findall("CutSetting")
        cells = project.findall("Shape")

        self.assertEqual(["0", "1", "2"], [layer.find("index").attrib["Value"] for layer in layers])
        self.assertEqual(["Coupon labels", "Red", "Blue"], [layer.find("name").attrib["Value"] for layer in layers])
        self.assertEqual(["500", "500", "900"], [layer.find("speed").attrib["Value"] for layer in layers])
        self.assertEqual(["1", "2"], [cell.attrib["CutIndex"] for cell in cells])
        self.assertTrue(all(cell.attrib["W"] == "10" and cell.attrib["H"] == "10" for cell in cells))

        text = project.findall("Shape[@Type='Text']")
        self.assertEqual(["0", "0", "0"], [item.attrib["CutIndex"] for item in text])
        self.assertEqual(["Material Library Settings", "Red", "Blue"], [item.attrib["Str"] for item in text])

    def test_coupon_scales_complete_layout_to_requested_dimensions(self):
        library = ET.fromstring("""
            <LightBurnLibrary><Material name="steel">
              <Entry Desc="Black"><CutSetting type="Scan"><index Value="0"/><name Value="Black"/></CutSetting></Entry>
            </Material></LightBurnLibrary>
        """)
        project = material_coupon_project(library, coupon_width_mm=50, coupon_length_mm=25)
        cell = project.find("Shape[@Type='Rect']")
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

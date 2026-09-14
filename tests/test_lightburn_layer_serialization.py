import io
import tempfile
import unittest
from pathlib import Path

from lib.lightburn import FillLayer, Lightburn


class LightburnLayerSerializationTests(unittest.TestCase):
    def test_fill_layer_omits_missing_secondary_power(self):
        layer = FillLayer(1, "Blue", 5, 27)
        output = io.StringIO()

        layer.write(output)

        self.assertNotIn('<maxPower2', output.getvalue())

    def test_imported_scan_without_secondary_power_omits_the_element(self):
        library_xml = """\
<LightBurnLibrary>
  <Material name="steel">
    <Entry Desc="Blue">
      <CutSetting type="Scan">
        <maxPower Value="31"/>
      </CutSetting>
    </Entry>
  </Material>
</LightBurnLibrary>
"""
        with tempfile.TemporaryDirectory() as directory:
            library_path = Path(directory) / "hatch.clb"
            library_path.write_text(library_xml, encoding="utf-8")
            layer = Lightburn().parse_material_library(library_path)[0]

        output = io.StringIO()
        layer.write(output)

        self.assertNotIn('<maxPower2', output.getvalue())

    def test_explicit_secondary_power_is_preserved(self):
        layer = FillLayer(1, "Blue", 5, 27, maxPower2=19)
        output = io.StringIO()

        layer.write(output)

        self.assertIn('<maxPower2 Value="19"/>', output.getvalue())

    def test_fill_layer_omits_missing_q_pulse_width(self):
        layer = FillLayer(1, "Blue", 5, 27)
        output = io.StringIO()

        layer.write(output)

        self.assertNotIn('<QPulseWidth', output.getvalue())

    def test_imported_scan_without_q_pulse_width_omits_the_element(self):
        library_xml = """\
<LightBurnLibrary>
  <Material name="steel">
    <Entry Desc="dark-red">
      <CutSetting type="Scan"><frequency Value="110000"/></CutSetting>
    </Entry>
  </Material>
</LightBurnLibrary>
"""
        with tempfile.TemporaryDirectory() as directory:
            library_path = Path(directory) / "colors.clb"
            library_path.write_text(library_xml, encoding="utf-8")
            layer = Lightburn().parse_material_library(library_path)[0]

        output = io.StringIO()
        layer.write(output)

        self.assertIsNone(layer.QPulseWidth)
        self.assertNotIn('<QPulseWidth', output.getvalue())

    def test_explicit_q_pulse_width_is_preserved(self):
        layer = FillLayer(1, "Blue", 5, 27, qPulseWidth=4)
        output = io.StringIO()

        layer.write(output)

        self.assertIn('<QPulseWidth Value="4"/>', output.getvalue())

    def test_imported_offset_without_secondary_power_omits_the_element(self):
        library_xml = """\
<LightBurnLibrary>
  <Material name="steel">
    <Entry Desc="Blue">
      <CutSetting type="Offset"><maxPower Value="31"/></CutSetting>
    </Entry>
  </Material>
</LightBurnLibrary>
"""
        with tempfile.TemporaryDirectory() as directory:
            library_path = Path(directory) / "hatch.clb"
            library_path.write_text(library_xml, encoding="utf-8")
            layer = Lightburn().parse_material_library(library_path)[0]

        output = io.StringIO()
        layer.write(output)

        self.assertNotIn('<maxPower2', output.getvalue())

    def test_import_accepts_textual_lightburn_booleans(self):
        library_xml = """\
<LightBurnLibrary>
  <Material name="steel">
    <Entry Desc="White">
      <CutSetting type="Scan">
        <crossHatch Value="true"/>
        <bidir Value="TRUE"/>
        <hide Value="false"/>
        <negative Value="TRUE"/>
        <autoRotate Value="FALSE"/>
        <tabsEnabled Value="true"/>
      </CutSetting>
    </Entry>
  </Material>
</LightBurnLibrary>
"""
        with tempfile.TemporaryDirectory() as directory:
            library_path = Path(directory) / "text-booleans.clb"
            library_path.write_text(library_xml, encoding="utf-8")
            layer = Lightburn().parse_material_library(library_path)[0]

        self.assertIs(layer.crossHatch, True)
        self.assertIs(layer.bidir, True)
        self.assertIs(layer.hide, False)
        self.assertIs(layer.negative, True)
        self.assertIs(layer.autoRotate, False)
        self.assertIs(layer.tabsEnabled, True)

    def test_import_preserves_numeric_lightburn_boolean_behavior(self):
        library_xml = """\
<LightBurnLibrary>
  <Material name="steel">
    <Entry Desc="White">
      <CutSetting type="Scan"><crossHatch Value="1"/><bidir Value="0"/><hide Value="0"/></CutSetting>
    </Entry>
  </Material>
</LightBurnLibrary>
"""
        with tempfile.TemporaryDirectory() as directory:
            library_path = Path(directory) / "numeric-booleans.clb"
            library_path.write_text(library_xml, encoding="utf-8")
            layer = Lightburn().parse_material_library(library_path)[0]

        self.assertIs(layer.crossHatch, True)
        self.assertIs(layer.bidir, False)
        self.assertIs(layer.hide, False)

    def test_bidirectional_and_crosshatch_are_serialized_for_lightburn(self):
        layer = FillLayer(1, "Blue", 5, 27)
        layer.crossHatch = True
        layer.bidir = True
        output = io.StringIO()

        layer.write(output)

        self.assertIn('<crossHatch Value="1"/>', output.getvalue())
        self.assertIn('<bidir Value="1"/>', output.getvalue())

    def test_imported_fill_strategy_and_flood_fill_are_preserved(self):
        library_xml = """\
<LightBurnLibrary>
  <Material name="steel">
    <Entry Desc="Black">
      <CutSetting type="Scan"><scanOpt Value="individual"/><floodFill Value="1"/></CutSetting>
    </Entry>
  </Material>
</LightBurnLibrary>
"""
        with tempfile.TemporaryDirectory() as directory:
            library_path = Path(directory) / "flood-fill.clb"
            library_path.write_text(library_xml, encoding="utf-8")
            layer = Lightburn().parse_material_library(library_path)[0]

        output = io.StringIO()
        layer.write(output)

        self.assertEqual(layer.scanOpt, "individual")
        self.assertIs(layer.floodFill, True)
        self.assertIn('<scanOpt Value="individual"/>', output.getvalue())
        self.assertIn('<floodFill Value="1"/>', output.getvalue())

    def test_missing_fill_behavior_remains_omitted(self):
        layer = FillLayer(1, "Blue", 5, 27)
        output = io.StringIO()

        layer.write(output)

        self.assertNotIn("<scanOpt", output.getvalue())
        self.assertNotIn("<floodFill", output.getvalue())


if __name__ == "__main__":
    unittest.main()

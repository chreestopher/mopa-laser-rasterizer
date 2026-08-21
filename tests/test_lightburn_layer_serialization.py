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


if __name__ == "__main__":
    unittest.main()

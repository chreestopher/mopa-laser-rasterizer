import ast
import unittest
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
HANDLER = ROOT / "serverless_api" / "handler.py"


def load_blank_project_builder():
    tree = ast.parse(HANDLER.read_text(encoding="utf-8"))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "blank_lightburn_project"
    )
    namespace = {
        "ET": ET,
        "deepcopy": deepcopy,
        "PALETTE": [(f"Layer {index}", f"#{index:06X}") for index in range(30)],
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(HANDLER), "exec"), namespace)
    return namespace["blank_lightburn_project"]


def entry(name, linked=False):
    node = ET.Element("Entry", {"Desc": name})
    cut = ET.SubElement(node, "CutSetting", {"type": "Cut"})
    ET.SubElement(cut, "index", {"Value": "29"})
    ET.SubElement(cut, "name", {"Value": "Old name"})
    ET.SubElement(cut, "speed", {"Value": "100"})
    if linked:
        ET.SubElement(cut, "LinkPath", {"Value": "external.clb"})
    return node


class ServerlessBlankLightburnProjectTests(unittest.TestCase):
    def test_official_layers_are_reserved_before_overflow_is_assigned(self):
        build = load_blank_project_builder()
        project = build([
            (entry("Official Red"), 2),
            (entry("Custom"), None),
            (entry("Official Blue", linked=True), 1),
            (entry("Second Red"), 2),
        ])

        self.assertEqual(project.tag, "LightBurnProject")
        self.assertEqual(project.findall("./Shape"), [])
        layers = project.findall("./CutSetting")
        self.assertEqual(len(layers), 4)
        assignments = {
            layer.find("./name").get("Value"): int(layer.find("./index").get("Value"))
            for layer in layers
        }
        self.assertEqual(assignments, {
            "Custom": 0,
            "Official Blue": 1,
            "Official Red": 2,
            "Second Red": 3,
        })
        self.assertTrue(all(layer.find("./LinkPath") is None for layer in layers))

    def test_vault_exposes_and_downloads_blank_project_action(self):
        page = (ROOT / "serverless_web" / "vault.html").read_text(encoding="utf-8")
        script = (ROOT / "serverless_web" / "vault.js").read_text(encoding="utf-8")
        handler = HANDLER.read_text(encoding="utf-8")

        self.assertIn('value="blank_project">Generate Blank LightBurn Project', page)
        self.assertIn('.holographic-recipe-card .library-card-actions{justify-content:flex-start}', page)
        self.assertIn('.holographic-recipe-card .library-card-actions .deleteRecipe{margin-left:auto}', page)
        self.assertIn('projectDownload=action==="coupon"||action==="blank_project"', script)
        self.assertIn('blankProject?"Project name"', script)
        self.assertIn('blankProject?"Download blank project"', script)
        self.assertIn('swatch_hex:assignedEntryHex(library,entry)', script)
        self.assertIn('swatch_hex:official?.hex||""', script)
        self.assertIn('${selfContained?"Settings":"View"}', script)
        self.assertIn('if action == "blank_project":', handler)
        self.assertIn('Tagging="mopa-retention=job"', handler)


if __name__ == "__main__":
    unittest.main()

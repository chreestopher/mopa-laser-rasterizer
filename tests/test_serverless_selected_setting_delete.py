import ast
import io
import json
import time
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]


class ServerlessSelectedSettingDeleteTests(unittest.TestCase):
    def setUp(self):
        self.handler = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")
        self.page = (ROOT / "serverless_web" / "vault.html").read_text(encoding="utf-8")
        self.client = (ROOT / "serverless_web" / "vault.js").read_text(encoding="utf-8")

    def delete_function(self, objects, material=None, recipe=None, preferences=None):
        functions = [
            node for node in ast.parse(self.handler).body
            if isinstance(node, ast.FunctionDef) and node.name in {
                "delete_selected_palette_settings", "fauxlographic_schema_version",
            }
        ]

        class FakeS3:
            def __init__(self):
                self.objects = dict(objects)

            def get_object(self, Bucket, Key):
                return {"Body": io.BytesIO(self.objects[Key])}

            def put_object(self, Bucket, Key, Body, **_kwargs):
                self.objects[Key] = Body

        class FakeTable:
            def __init__(self):
                self.preferences = preferences or {}
                self.updates = []

            def get_item(self, **_kwargs):
                return {"Item": {"preferences": self.preferences}} if self.preferences else {}

            def update_item(self, **kwargs):
                self.updates.append(kwargs)

            def put_item(self, Item):
                self.preferences = Item["preferences"]

        fake_s3, fake_table = FakeS3(), FakeTable()

        def summary(contents):
            root = ET.fromstring(contents)
            entries = [entry for item in root.findall("./Material") for entry in item.findall("./Entry")]
            return {
                "entry_count": len(entries),
                "material_names": [item.get("name") for item in root.findall("./Material")],
                "entries": [],
            }

        namespace = {
            "json": json, "time": time, "ET": ET, "ClientError": Exception,
            "UnicodeDecodeError": UnicodeDecodeError, "MAX_MATERIAL_BYTES": 10_000,
            "MAX_RECIPE_BYTES": 10_000, "BUCKET": "test", "s3": fake_s3,
            "table": fake_table, "owned_material": lambda _owner, _id: material,
            "owned_recipe": lambda _owner, _id: recipe,
            "validate_library_descriptions": lambda _root: None,
            "material_summary": summary, "dynamo_value": lambda value: value,
            "clean_account_preferences": lambda value: value,
            "holographic_swatch_preview": lambda values: [item["observed_hex"] for item in values],
            "response": lambda status, body: {"statusCode": status, "body": json.dumps(body)},
        }
        exec(compile(ast.Module(body=functions, type_ignores=[]), "handler.py", "exec"), namespace)
        return namespace["delete_selected_palette_settings"], fake_s3, fake_table

    def test_sources_parse_and_delete_uses_existing_authenticated_endpoint(self):
        ast.parse(self.handler)
        self.assertIn('<option value="delete">Delete selected settings</option>', self.page)
        self.assertIn('if action == "delete":', self.handler)
        self.assertIn('return delete_selected_palette_settings(owner, data.get("selections"))', self.handler)
        self.assertIn('rawApi("/account/material-libraries/selected-settings"', self.client)

    def test_delete_is_confirmed_and_submission_is_locked(self):
        self.assertIn("This cannot be undone", self.client)
        self.assertIn('runButton.classList.toggle("danger",deleting)', self.client)
        self.assertIn("runButton.disabled=true", self.client)
        self.assertIn("finally{runButton.disabled=false}", self.client)
        self.assertIn('materialField.hidden=deleting||destinationMaterial', self.client)

    def test_action_specific_fields_are_actually_hidden(self):
        self.assertIn(".selected-actions-form [hidden]{display:none!important}", self.page)
        self.assertIn('document.querySelector("#couponFields").hidden=action!=="coupon"', self.client)
        self.assertIn('document.querySelector("#existingLibraryField").hidden=!destinationMaterial', self.client)
        self.assertIn('document.querySelector("#newLibraryField").hidden=action!=="copy_new"', self.client)
        self.assertIn("materialField.hidden=deleting||destinationMaterial", self.client)

    def test_all_lightburn_palettes_enforce_one_destination_material(self):
        helper = self.handler[
            self.handler.index("def single_palette_material"):
            self.handler.index("def edit_material_entry")
        ]
        self.assertIn('len(materials) != 1', helper)
        self.assertIn('must contain settings for exactly one material', helper)
        summary = self.handler[
            self.handler.index("def material_summary"):
            self.handler.index("def retain_selected_material")
        ]
        self.assertIn("len(populated_materials) != 1", summary)

    def test_copy_existing_uses_destination_material_not_form_value(self):
        function = self.handler[
            self.handler.index("def selected_material_settings"):
            self.handler.index("def holographic_svg_grid")
        ]
        lookup = function.index('if action == "copy_existing":')
        build = function.index("root = selected_settings_root")
        self.assertLess(lookup, build)
        self.assertIn('destination, material_name = single_palette_material(target_root, "Destination palette")', function)
        copy_block = function[function.rindex('if action == "copy_existing":'):]
        self.assertIn("destination.extend", copy_block)
        self.assertNotIn("ET.SubElement", copy_block)
        self.assertIn('":material":material_name', copy_block)
        self.assertIn('destinationMaterial=action==="copy_existing"', self.client)
        self.assertIn("materialName.required=!deleting&&!destinationMaterial", self.client)

    def test_inline_edit_cannot_move_setting_to_another_material(self):
        function = self.handler[
            self.handler.index("def edit_material_entry"):
            self.handler.index("LIGHTBURN_SETTING_FIELD_ORDER")
        ]
        self.assertIn('destination, material_name = single_palette_material(root, "Destination palette")', function)
        self.assertNotIn('data.get("material")', function)
        self.assertNotIn('ET.SubElement(root, "Material"', function)

    def test_palette_card_edits_one_material_for_every_setting(self):
        rename = self.handler[
            self.handler.index("def rename_material"):
            self.handler.index("def single_palette_material")
        ]
        self.assertIn('material_name = str(data.get("material_name") or old_material_name)', rename)
        self.assertIn('material.set("name", material_name)', rename)
        self.assertIn('for link in material.findall(".//LinkPath")', rename)
        self.assertIn('material_name + value[len(old_material_name):]', rename)
        self.assertIn('material_name=:material, summary=:summary', rename)
        self.assertIn('class="paletteMaterialName"', self.client)
        self.assertIn('materialName=card.querySelector(".paletteMaterialName").value.trim()', self.client)
        self.assertIn('material_name:materialName', self.client)
        save_handler = self.client[
            self.client.index("materials.onclick=async event=>"):
            self.client.index('materials.addEventListener("click"')
        ]
        self.assertNotIn('editor.querySelector(".editMaterial").value', save_handler)
        self.assertNotIn('class="editMaterial"', self.client)
        self.assertNotIn('querySelectorAll(".editMaterial")', self.client)
        self.assertIn('card.querySelector(".palette-kind")?.insertAdjacentHTML("afterend"', self.client)
        material_card = self.client[
            self.client.index("function materialCard"):
            self.client.index("function updateSelectedControls")
        ]
        self.assertNotIn('${esc(entry.material)} · ${esc(entry.type)}', material_card)
        self.assertIn('<span class="muted">${esc(entry.type)}</span>', material_card)

    def test_selected_swatches_include_identity_for_safe_retries(self):
        self.assertIn("entry_description:entry.description", self.client)
        self.assertIn("recipe_name:recipe.name,recipe_hex:recipe.observed_hex", self.client)
        function = self.handler[
            self.handler.index("def delete_selected_palette_settings"):
            self.handler.index("def selected_material_settings")
        ]
        self.assertIn("selected settings changed; reload the palette", function)
        self.assertIn("selected swatches changed; reload the palette", function)
        self.assertIn("not isinstance(entry_id, bool)", function)
        self.assertIn("not isinstance(recipe_index, bool)", function)

    def test_material_and_holographic_palettes_cannot_be_emptied(self):
        function = self.handler[
            self.handler.index("def delete_selected_palette_settings"):
            self.handler.index("def selected_material_settings")
        ]
        self.assertIn("len(entries) - len(entry_ids) < 1", function)
        self.assertIn("Keep at least one setting", function)
        self.assertIn("len(measured) - len(recipe_indexes) < 1", function)
        self.assertIn("Keep at least one swatch", function)

    def test_persisted_files_metadata_previews_and_assignments_are_updated(self):
        function = self.handler[
            self.handler.index("def delete_selected_palette_settings"):
            self.handler.index("def selected_material_settings")
        ]
        self.assertIn("material.remove(entry)", function)
        self.assertIn("root.remove(material)", function)
        self.assertIn('profile["recipes"] = kept', function)
        self.assertIn('"swatch_preview": holographic_swatch_preview(kept)', function)
        self.assertIn('preferences.get("material_library_color_assignments")', function)
        self.assertIn('"deleted_settings": deleted_count', function)
        self.assertIn('if(action==="copy_existing"||action==="copy_new"||action==="delete")await reload()', self.client)

    def test_material_setting_delete_executes_and_removes_empty_material(self):
        source = (
            b'<LightBurnLibrary><Material name="First"><Entry Desc="Red" /></Material>'
            b'<Material name="Second"><Entry Desc="Blue" /><Entry Desc="Green" /></Material>'
            b'</LightBurnLibrary>'
        )
        record = {"name": "Colors", "s3_key": "library.clb"}
        preferences = {"material_library_color_assignments": {
            "library": {"#FF0000": "Red", "#0000FF": "Blue"}
        }}
        delete, fake_s3, fake_table = self.delete_function(
            {"library.clb": source}, material=record, preferences=preferences
        )
        result = delete("owner", [{
            "library_id": "library", "entry_id": 0, "entry_description": "Red"
        }])
        root = ET.fromstring(fake_s3.objects["library.clb"])
        self.assertEqual([item.get("name") for item in root.findall("./Material")], ["Second"])
        self.assertEqual([item.get("Desc") for item in root.findall(".//Entry")], ["Blue", "Green"])
        self.assertEqual(json.loads(result["body"])["deleted_settings"], 1)
        self.assertNotIn("#FF0000", fake_table.preferences["material_library_color_assignments"]["library"])

    def test_holographic_swatch_delete_executes_and_refreshes_metadata(self):
        profile = {"schema_version": 2, "recipes": [
            {"name": "A", "observed_hex": "#112233"},
            {"name": "B", "observed_hex": "#445566"},
        ]}
        record = {"name": "Holographic", "s3_key": "palette.json", "metadata": {}}
        delete, fake_s3, fake_table = self.delete_function(
            {"palette.json": json.dumps(profile).encode()}, recipe=record
        )
        result = delete("owner", [{
            "recipe_id": "recipe", "recipe_index": 0,
            "recipe_name": "A", "recipe_hex": "#112233",
        }])
        stored = json.loads(fake_s3.objects["palette.json"])
        self.assertEqual([item["name"] for item in stored["recipes"]], ["B"])
        metadata = fake_table.updates[0]["ExpressionAttributeValues"][":metadata"]
        self.assertEqual(metadata["recipe_count"], 1)
        self.assertEqual(metadata["swatch_preview"], ["#445566"])
        self.assertEqual(json.loads(result["body"])["updated_palettes"], 1)


if __name__ == "__main__":
    unittest.main()

"""Fauxlographic palettes must fit the available LightBurn layers."""

import ast
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import time
from xml.etree import ElementTree as ET
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]


def load_palette_builder():
    path = ROOT / "serverless_api" / "handler.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {
        "fauxlographic_swatch_capacity",
        "fauxlographic_swatch_limit_message",
        "fauxlographic_schema_version",
        "usable_preserved_black_setting",
        "validate_lightburn_setting_snapshot",
        "uploaded_holographic_settings_root",
        "save_measured_holographic_recipe",
        "update_holographic_recipe",
    }
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = {
        "ET": ET,
        "MAX_LIGHTBURN_LAYERS": 30,
        "lightburn_snapshot_element": lambda _snapshot: ET.Element("CutSetting", {"type": "Cut"}),
        "nearest_lightburn_palette_index": lambda _hex: 1,
        "user_id": lambda _event: "test-owner",
        "body_json": lambda event: event,
        "uuid": uuid,
        "json_value": lambda value: value,
        "json": json,
        "math": math,
        "re": re,
        "MAX_RECIPE_BYTES": 10 * 1024 * 1024,
        "BUCKET": "test-bucket",
        "ClientError": Exception,
    }
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


def profile(count, black=False):
    return {
        "kind": "holographic_calibration_profile",
        "schema_version": 2,
        "recipes": [
            {"name": f"Swatch {index}", "observed_hex": "#0000FF", "laser_settings": {"type": "Cut", "settings": {}}}
            for index in range(count)
        ],
        "black_setting": {"laser_settings": {"type": "Cut", "settings": {}}} if black else None,
    }


class FauxlographicSwatchLimitTests(unittest.TestCase):
    def test_bulk_delete_identifies_unreadable_swatch_and_palette(self):
        namespace = load_palette_builder()

        class StoredPalette:
            def get_object(self, **_kwargs):
                return {"Body": self}

            def read(self, _limit):
                return json.dumps({"schema_version": 2, "recipes": [{"name": "A"}, None]}).encode()

        namespace["s3"] = StoredPalette()
        namespace["owned_recipe"] = lambda _owner, _recipe_id: {"s3_key": "palette.json", "name": "Test palette"}
        path = ROOT / "serverless_api" / "handler.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "delete_selected_palette_settings")
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
        selected = [{"recipe_id": "palette-id", "recipe_index": 1, "recipe_name": "B", "recipe_hex": "#000000"}]
        with self.assertRaisesRegex(ValueError, "Swatch 2 in Fauxlographic Palette 'Test palette'.*Reload the Vault"):
            namespace["delete_selected_palette_settings"]("owner", selected)
        namespace["owned_recipe"] = lambda _owner, _recipe_id: None
        with self.assertRaisesRegex(ValueError, "no longer exists.*Reload the Vault, select the settings again"):
            namespace["delete_selected_palette_settings"]("owner", selected)
        namespace["owned_recipe"] = lambda _owner, _recipe_id: {"s3_key": "palette.json", "name": "Test palette"}
        selected[0]["recipe_index"] = 3
        with self.assertRaisesRegex(ValueError, "swatches no longer exists.*Reload the Vault, select the settings again"):
            namespace["delete_selected_palette_settings"]("owner", selected)
        namespace["owned_material"] = lambda _owner, _library_id: None
        selected_library = [{"library_id": "library-id", "entry_id": 0, "entry_description": "Red"}]
        with self.assertRaisesRegex(ValueError, "Material Libraries no longer exists.*Reload the Vault, select the settings again"):
            namespace["delete_selected_palette_settings"]("owner", selected_library)
        namespace["owned_material"] = lambda _owner, _library_id: {"s3_key": "library.clb"}

        class EmptyLibrary:
            def get_object(self, **_kwargs):
                return {"Body": self}

            def read(self, _limit):
                return b"<LightBurnLibrary><Material name='Test'/></LightBurnLibrary>"

        namespace["s3"] = EmptyLibrary()
        namespace["MAX_MATERIAL_BYTES"] = 10 * 1024 * 1024
        with self.assertRaisesRegex(ValueError, "Material Library settings no longer exists.*Reload the Vault, select the settings again"):
            namespace["delete_selected_palette_settings"]("owner", selected_library)

    def test_saved_palette_open_and_edit_errors_suggest_vault_reload(self):
        namespace = load_palette_builder()

        class UnavailableS3:
            def get_object(self, **_kwargs):
                raise OSError("Stored object unavailable")

        namespace["s3"] = UnavailableS3()
        namespace["owned_recipe"] = lambda _owner, _recipe_id: {"s3_key": "palette.json"}
        path = ROOT / "serverless_api" / "handler.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in {
            "holographic_recipe_detail", "update_holographic_recipe",
        }]
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec"), namespace)
        for name in ("holographic_recipe_detail", "update_holographic_recipe"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "Reload the Vault.*report the palette name"):
                namespace[name]({}, "palette-id")

    def test_editor_identifies_invalid_interval_and_angle(self):
        namespace = load_palette_builder()

        class SavedPalette:
            def get_object(self, **_kwargs):
                return {"Body": self}

            def read(self, _limit):
                return json.dumps({"black_setting": None}).encode()

        namespace["s3"] = SavedPalette()
        namespace["owned_recipe"] = lambda _owner, _recipe_id: {"s3_key": "test-palette"}
        update = namespace["update_holographic_recipe"]
        swatch = {"name": "Blue", "observed_hex": "#0000FF", "interval_mm": "bad", "angle_degrees": 30}
        with self.assertRaisesRegex(ValueError, "Swatch 'Blue'.*Interval \\(mm\\)"):
            update({"name": "Palette", "recipes": [swatch]}, "recipe-id")
        swatch["interval_mm"] = 0.05
        swatch["angle_degrees"] = "bad"
        with self.assertRaisesRegex(ValueError, "Swatch 'Blue'.*Angle \\(degrees\\)"):
            update({"name": "Palette", "recipes": [swatch]}, "recipe-id")
        with self.assertRaisesRegex(ValueError, "Swatch 1 .*Reload the Vault palette"):
            update({"name": "Palette", "recipes": [None]}, "recipe-id")

        def invalid_snapshot(_snapshot):
            raise ValueError("Invalid embedded setting")

        namespace["validate_lightburn_setting_snapshot"] = invalid_snapshot
        swatch["angle_degrees"] = 30
        with self.assertRaisesRegex(ValueError, "Swatch 'Blue'.*Vault editor"):
            update({"name": "Palette", "recipes": [swatch]}, "recipe-id")

    def test_uploaded_palette_identifies_unreadable_swatch_position(self):
        build = load_palette_builder()["uploaded_holographic_settings_root"]
        uploaded = profile(3)
        uploaded["recipes"][1] = None
        with self.assertRaisesRegex(ValueError, "Swatch 2 .*Check the JSON file"):
            build(uploaded, [1], "Palette")

    def test_uploaded_palette_distinguishes_unnamed_and_duplicate_swatches(self):
        build = load_palette_builder()["uploaded_holographic_settings_root"]
        uploaded = profile(3)
        uploaded["recipes"][1]["name"] = ""
        with self.assertRaisesRegex(ValueError, "Swatch 2 .*has no name"):
            build(uploaded, [1], "Palette")
        uploaded["recipes"][1]["name"] = "swatch 0"
        with self.assertRaisesRegex(ValueError, "Swatches 1 and 2 .*both use the name"):
            build(uploaded, [0, 1], "Palette")

    def test_uploaded_palette_identifies_invalid_embedded_setting(self):
        namespace = load_palette_builder()

        def invalid_snapshot(_snapshot):
            raise ValueError("Invalid embedded setting")

        namespace["lightburn_snapshot_element"] = invalid_snapshot
        build = namespace["uploaded_holographic_settings_root"]
        with self.assertRaisesRegex(ValueError, "Swatch 2 .*invalid embedded LightBurn settings"):
            build(profile(2), [1], "Palette")

    def test_import_error_identifies_unreadable_swatch_position(self):
        source = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")
        self.assertIn(
            'raise ValueError(f"Swatch {swatch_index} in the uploaded Fauxlographic Palette could not be read.',
            source,
        )

    def test_invalid_measurement_identifies_cell_when_possible(self):
        namespace = load_palette_builder()

        class CalibrationTable:
            def get_item(self, **_kwargs):
                return {"Item": {"metadata": {"cells": [{"index": 7}]}}}

        namespace["table"] = CalibrationTable()
        save = namespace["save_measured_holographic_recipe"]
        event = {"calibration_id": str(uuid.uuid4()), "measurements": [{"index": 7, "observed_rgb": ["bad", 0, 0]}]}
        with self.assertRaisesRegex(ValueError, "Cell 7 .*Measure again"):
            save(event)
        event["measurements"] = [{"observed_rgb": [0, 0, 0]}]
        with self.assertRaisesRegex(ValueError, "A selected cell .*Measure again"):
            save(event)

    def test_thirty_swatches_fit_without_separate_black(self):
        build = load_palette_builder()["uploaded_holographic_settings_root"]
        root = build(profile(30), list(range(30)), "Palette")
        self.assertEqual(len(root.findall("./Material/Entry")), 30)

    def test_preserved_black_reserves_one_of_thirty_layers(self):
        build = load_palette_builder()["uploaded_holographic_settings_root"]
        root = build(profile(29, black=True), list(range(29)), "Palette")
        self.assertEqual(len(root.findall("./Material/Entry")) + 1, 30)
        with self.assertRaisesRegex(ValueError, "at most 29 measured swatches"):
            build(profile(30, black=True), list(range(30)), "Palette")

    def test_unreadable_preserved_black_does_not_take_a_layer(self):
        namespace = load_palette_builder()
        uploaded = profile(30, black=True)
        uploaded["black_setting"]["laser_settings"] = {"type": "Cut", "settings": []}
        self.assertIsNone(namespace["usable_preserved_black_setting"](uploaded["black_setting"]))
        self.assertEqual(namespace["fauxlographic_swatch_capacity"](uploaded["black_setting"]), 30)
        root = namespace["uploaded_holographic_settings_root"](uploaded, list(range(30)), "Palette")
        self.assertEqual(len(root.findall("./Material/Entry")), 30)

    def test_import_keeps_palette_but_drops_unreadable_preserved_black(self):
        namespace = load_palette_builder()
        path = ROOT / "serverless_api" / "handler.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "finalize_import")
        imported = profile(30, black=True)
        imported["black_setting"]["laser_settings"] = {"type": "Cut", "settings": []}
        source = json.dumps(imported).encode()

        class ImportS3:
            def __init__(self):
                self.puts = []
                self.copies = []
                self.upload_capability = "cap"
                self.unavailable = False
                self.reported_size = None

            def get_object(self, **_kwargs):
                if self.unavailable:
                    raise OSError("Object unavailable")
                return {"Metadata": {"upload-capability": self.upload_capability},
                        "ContentLength": len(source) if self.reported_size is None else self.reported_size, "Body": self}

            def read(self, _limit):
                return source

            def put_object(self, **kwargs):
                self.puts.append(kwargs)

            def copy_object(self, **kwargs):
                self.copies.append(kwargs)

            def delete_object(self, **_kwargs):
                pass

        class ImportTable:
            def __init__(self):
                self.saved = None
                self.kind = "recipe"
                self.library_intent = None
                self.base_setting_id = None
                self.hatch_operation = None

            def get_item(self, **_kwargs):
                return {"Item": {"kind": self.kind, "capability": "cap", "s3_key": "temporary", "filename": "palette.json",
                                 "library_intent": self.library_intent, "base_setting_id": self.base_setting_id,
                                 "material_name": "Steel", "hatch_operation": self.hatch_operation}}

            def put_item(self, **kwargs):
                self.saved = kwargs["Item"]

            def delete_item(self, **_kwargs):
                pass

        s3 = ImportS3()
        table = ImportTable()

        def retained_material(contents, _name):
            ET.fromstring(contents)
            return contents

        namespace.update({
            "s3": s3, "table": table, "secrets": secrets, "token_hash": lambda _token: "cap",
            "time": time, "os": os, "hashlib": hashlib, "MAX_MATERIAL_BYTES": 10 * 1024 * 1024,
            "holographic_swatch_preview": lambda _recipes: [], "safe_name": lambda name, _fallback: name,
            "response": lambda _status, body: body,
            "retain_selected_material": retained_material,
        })
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
        invalid_session = namespace["finalize_import"]({}, "import-id")
        self.assertIn("Start a new import and upload the file using its new link", invalid_session["message"])
        result = namespace["finalize_import"]({"upload_token": "ok"}, "import-id")
        self.assertTrue(result["ignored_preserved_black"])
        self.assertFalse(result["holographic_recipe"]["metadata"]["has_black_setting"])
        self.assertIsNone(json.loads(s3.puts[0]["Body"])["black_setting"])
        self.assertFalse(s3.copies)
        self.assertEqual(table.saved["metadata"]["recipe_count"], 30)
        source = b""
        with self.assertRaisesRegex(ValueError, "uploaded file is empty.*Choose a nonempty file and start a new import"):
            namespace["finalize_import"]({"upload_token": "ok"}, "import-id")
        s3.reported_size = 1
        with self.assertRaisesRegex(ValueError, "uploaded file is empty.*Choose a nonempty file and start a new import"):
            namespace["finalize_import"]({"upload_token": "ok"}, "import-id")
        s3.reported_size = None

        for invalid_file in ([], {"kind": "another_file", "recipes": [{}]}):
            source = json.dumps(invalid_file).encode()
            with self.assertRaisesRegex(ValueError, "This file is not a Fauxlographic Palette"):
                namespace["finalize_import"]({"upload_token": "ok"}, "import-id")
        source = json.dumps({"kind": "holographic_calibration_profile", "recipes": []}).encode()
        with self.assertRaisesRegex(ValueError, "has no saved swatches"):
            namespace["finalize_import"]({"upload_token": "ok"}, "import-id")
        bad_version = profile(1)
        bad_version["schema_version"] = "not-a-version"
        source = json.dumps(bad_version).encode()
        with self.assertRaisesRegex(ValueError, "invalid file version"):
            namespace["finalize_import"]({"upload_token": "ok"}, "import-id")
        source = b"{not valid JSON"
        with self.assertRaisesRegex(ValueError, "Fauxlographic Palette JSON could not be read.*start the import again"):
            namespace["finalize_import"]({"upload_token": "ok"}, "import-id")
        table.kind = "material"
        source = b"<LightBurnLibrary><Material"
        with self.assertRaisesRegex(ValueError, "LightBurn Material Library could not be read.*start the import again"):
            namespace["finalize_import"]({"upload_token": "ok"}, "import-id")
        source = b'<LightBurnLibrary><Material name="Steel"><Entry Desc="Red"><CutSetting type="Scan"/></Entry></Material></LightBurnLibrary>'
        table.library_intent = "hatch_palette"
        table.base_setting_id = 2
        with self.assertRaisesRegex(ValueError, "Hatch Palette base setting no longer exists.*Start a new import"):
            namespace["finalize_import"]({"upload_token": "ok"}, "import-id")
        source = b'<LightBurnLibrary><Material name="Steel"><Entry Desc="Red"/></Material></LightBurnLibrary>'
        table.base_setting_id = 0
        table.hatch_operation = "Scan"
        with self.assertRaisesRegex(ValueError, "Hatch Palette base entry has no LightBurn cut setting.*Fill or Offset Fill.*start a new import"):
            namespace["finalize_import"]({"upload_token": "ok"}, "import-id")
        table.base_setting_id = "not-a-setting"
        with self.assertRaisesRegex(ValueError, "Hatch Palette base setting selection could not be read.*Start a new import"):
            namespace["finalize_import"]({"upload_token": "ok"}, "import-id")
        s3.upload_capability = "another-session"
        with self.assertRaisesRegex(ValueError, "couldn't verify this uploaded file.*Start a new import.*new link"):
            namespace["finalize_import"]({"upload_token": "ok"}, "import-id")
        s3.unavailable = True
        with self.assertRaisesRegex(ValueError, "couldn't retrieve the uploaded file.*Start a new import.*upload the file again"):
            namespace["finalize_import"]({"upload_token": "ok"}, "import-id")
        s3.unavailable = False
        s3.upload_capability = "cap"
        namespace["MAX_MATERIAL_BYTES"] = 128
        source = b"x" * 129
        for kind, expected in (("material", "remove materials you don't plan to import"),
                               ("recipe", "only the swatches and capture details you need")):
            table.kind = kind
            for reported_size in (None, 128):
                s3.reported_size = reported_size
                with self.subTest(kind=kind, reported_size=reported_size), self.assertRaisesRegex(ValueError, expected):
                    namespace["finalize_import"]({"upload_token": "ok"}, "import-id")

    def test_import_upload_preflight_uses_server_size_limit(self):
        handler = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")
        vault = (ROOT / "serverless_web" / "vault.js").read_text(encoding="utf-8")
        self.assertIn('"max_file_bytes": MAX_MATERIAL_BYTES', handler)
        self.assertIn('file.size>target.max_file_bytes', vault)
        self.assertIn('importSizeMessage(target.kind,target.max_file_bytes)', vault)

    def test_uploaded_palette_has_useful_invalid_version_error(self):
        build = load_palette_builder()["uploaded_holographic_settings_root"]
        uploaded = profile(1)
        uploaded["schema_version"] = "not-a-version"
        with self.assertRaisesRegex(ValueError, "invalid file version"):
            build(uploaded, [0], "Palette")

    def test_invalid_index_is_not_reported_as_too_many_swatches(self):
        build = load_palette_builder()["uploaded_holographic_settings_root"]
        with self.assertRaisesRegex(ValueError, "no longer available"):
            build(profile(2), [5], "Palette")

    def test_all_entry_points_enforce_the_palette_capacity(self):
        source = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")
        for fragment in (
            "len(measurements) > fauxlographic_swatch_capacity(black_setting)",
            "len(measured) > capacity",
            "len(recipes) > fauxlographic_swatch_capacity(black_setting)",
            "len(measured) > fauxlographic_swatch_capacity(profile.get(\"black_setting\"))",
        ):
            self.assertIn(fragment, source)


if __name__ == "__main__":
    unittest.main()

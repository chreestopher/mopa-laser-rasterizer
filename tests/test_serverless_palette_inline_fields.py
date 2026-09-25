import ast
import io
import json
import re
import time
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]


def test_color_palette_inline_editor_uses_fixed_public_setting_contract():
    script = (ROOT / "serverless_web" / "vault.js").read_text(encoding="utf-8")
    page = (ROOT / "serverless_web" / "vault.html").read_text(encoding="utf-8")

    expected = (
        'label:"Min Power",keys:["minPower"]',
        'label:"Max Power",keys:["maxPower"]',
        'label:"Speed",keys:["speed"]',
        'label:"Frequency",keys:["frequency"]',
        'label:"QPulse Duration",keys:["QPulseWidth","qPulseDuration","qPulseWidth"]',
        'label:"Line Interval",keys:["interval"]',
        'label:"Scan Angle",keys:["angle"]',
        'label:"Angles per Pass",keys:["anglePerPass"]',
        'label:"Bidirectional",keys:["bidir"],options:[["0","Off"],["1","On"]]',
        'label:"Cross Hatch",keys:["crossHatch"],options:[["0","Off"],["1","On"]]',
        'label:"Fill Strategy",keys:["scanOpt"],exactOptions:true,options:[["","Fill all shapes"],["byGroup","Fill groups together"],["individual","Fill individual shapes"]]',
        'label:"Flood Fill",keys:["floodFill"],exactOptions:true,options:[["","Off"],["1","On"]]',
        'label:"Passes",keys:["numPasses"]',
    )
    for declaration in expected:
        assert declaration in script

    assert "colorPaletteSettingMarkup(settings)" in script
    assert 'library.library_intent==="hatch_palette"?importedSettingMarkup(settings):colorPaletteSettingMarkup(settings)' in script
    assert "<label>Cut Mode<select" in script
    assert 'src="/vault.js?v=13"' in page
    assert 'return [["","Not specified"],...field.options]' in script
    assert 'normalized==="true"' in script
    assert 'normalized==="false"' in script
    assert 'Number(normalized)===0' in script
    assert 'value=storedValue!==""?storedValue:String(field.defaultValue??"")' in script


def test_missing_scan_pulse_width_remains_unspecified():
    handler_path = ROOT / "serverless_api" / "handler.py"
    tree = ast.parse(handler_path.read_text(encoding="utf-8"))
    names = {
        "effective_lightburn_settings",
        "material_summary",
    }
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    namespace = {"ET": ET}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(handler_path), "exec"), namespace)
    source = b'''<LightBurnLibrary><Material name="steel"><Entry Desc="dark-red"><CutSetting type="Scan"><frequency Value="110000"/></CutSetting></Entry></Material></LightBurnLibrary>'''

    summary = namespace["material_summary"](source)
    assert "QPulseWidth" not in summary["entries"][0]["settings"]
    assert "target.append(deepcopy(entry))" in handler_path.read_text(encoding="utf-8")


def test_explicit_pulse_width_is_reported_unchanged():
    handler_path = ROOT / "serverless_api" / "handler.py"
    tree = ast.parse(handler_path.read_text(encoding="utf-8"))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "effective_lightburn_settings"
    )
    namespace = {"ET": ET}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(handler_path), "exec"), namespace)
    setting = ET.fromstring('<CutSetting type="Scan"><QPulseWidth Value="4"/></CutSetting>')

    values = namespace["effective_lightburn_settings"](setting)

    assert values["QPulseWidth"] == "4"


def test_color_palette_editor_explicitly_removes_a_cleared_optional_field():
    script = (ROOT / "serverless_web" / "vault.js").read_text(encoding="utf-8")

    assert 'unsetSettings=inputs.filter(input=>input.value===""' in script
    assert 'unset_settings:unsetSettings' in script


def test_hidden_imported_fields_remain_preserved_by_server_patch():
    handler = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")

    assert "for name, value in settings.items():" in handler
    assert "for name in unset_settings:" in handler


def test_link_path_is_not_exposed_in_any_palette_inline_editor():
    script = (ROOT / "serverless_web" / "vault.js").read_text(encoding="utf-8")

    assert 'hidden=new Set(["LinkPath"])' in script


def test_server_patch_writes_bidirectional_and_crosshatch_values():
    handler = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")
    function = next(
        node for node in ast.parse(handler).body
        if isinstance(node, ast.FunctionDef) and node.name == "edit_material_entry"
    )
    source = b'''<LightBurnLibrary><Material name="steel"><Entry Desc="Red"><CutSetting type="Scan"><bidir Value="0"/><crossHatch Value="1"/></CutSetting></Entry></Material></LightBurnLibrary>'''

    class FakeS3:
        def __init__(self):
            self.contents = source

        def get_object(self, **_kwargs):
            return {"Body": io.BytesIO(self.contents)}

        def put_object(self, **kwargs):
            self.contents = kwargs["Body"]

    class FakeTable:
        def update_item(self, **_kwargs):
            return None

    fake_s3 = FakeS3()
    namespace = {
        "ET": ET, "re": re, "time": time, "s3": fake_s3, "table": FakeTable(),
        "BUCKET": "test", "MAX_MATERIAL_BYTES": 10_000,
        "user_id": lambda _event: "owner",
        "body_json": lambda _event: {"description": "Red", "type": "Scan", "settings": {"bidir": "1", "crossHatch": "0"}},
        "owned_material": lambda _owner, _library_id: {"s3_key": "palette.clb"},
        "single_palette_material": lambda root, _context: (root.find("./Material"), "steel"),
        "material_summary": lambda _contents: {"entry_count": 1, "material_names": ["steel"], "entries": []},
        "dynamo_value": lambda value: value,
        "preserve_material_assignment_names": lambda *_args: None,
        "public_library_summary": lambda value: value,
        "response": lambda status, body: {"statusCode": status, "body": json.dumps(body)},
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), "handler.py", "exec"), namespace)

    result = namespace["edit_material_entry"]({}, "library", 0)
    cut = ET.fromstring(fake_s3.contents).find("./Material/Entry/CutSetting")

    assert result["statusCode"] == 200
    assert cut.find("./bidir").get("Value") == "1"
    assert cut.find("./crossHatch").get("Value") == "0"


def test_server_patch_can_change_or_remove_fill_behavior_without_touching_hidden_fields():
    handler = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")
    function = next(
        node for node in ast.parse(handler).body
        if isinstance(node, ast.FunctionDef) and node.name == "edit_material_entry"
    )
    source = b'''<LightBurnLibrary><Material name="steel"><Entry Desc="Black"><CutSetting type="Scan"><scanOpt Value="individual"/><floodFill Value="1"/><LinkPath Value="private-device-path"/></CutSetting></Entry></Material></LightBurnLibrary>'''

    class FakeS3:
        def __init__(self):
            self.contents = source

        def get_object(self, **_kwargs):
            return {"Body": io.BytesIO(self.contents)}

        def put_object(self, **kwargs):
            self.contents = kwargs["Body"]

    class FakeTable:
        def update_item(self, **_kwargs):
            return None

    fake_s3 = FakeS3()
    namespace = {
        "ET": ET, "re": re, "time": time, "s3": fake_s3, "table": FakeTable(),
        "BUCKET": "test", "MAX_MATERIAL_BYTES": 10_000,
        "user_id": lambda _event: "owner",
        "body_json": lambda _event: {
            "description": "Black", "type": "Scan",
            "settings": {"scanOpt": "byGroup"}, "unset_settings": ["floodFill"],
        },
        "owned_material": lambda _owner, _library_id: {"s3_key": "palette.clb"},
        "single_palette_material": lambda root, _context: (root.find("./Material"), "steel"),
        "material_summary": lambda _contents: {"entry_count": 1, "material_names": ["steel"], "entries": []},
        "dynamo_value": lambda value: value,
        "preserve_material_assignment_names": lambda *_args: None,
        "public_library_summary": lambda value: value,
        "response": lambda status, body: {"statusCode": status, "body": json.dumps(body)},
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), "handler.py", "exec"), namespace)

    namespace["edit_material_entry"]({}, "library", 0)
    cut = ET.fromstring(fake_s3.contents).find("./Material/Entry/CutSetting")

    assert cut.find("./scanOpt").get("Value") == "byGroup"
    assert cut.find("./floodFill") is None
    assert cut.find("./LinkPath").get("Value") == "private-device-path"

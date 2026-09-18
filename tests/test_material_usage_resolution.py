import services
from pathlib import Path
import re
import threading


def test_material_usage_resolution_uses_lightburn_parser(monkeypatch):
    class Setting:
        def __init__(self):
            self.materialName = "Stainless Steel"
            self.entryDesc = "Dark-Orange"
            self.name = "Dark-Orange"
            self.type = "Scan"
            self.subLayers = []
            self.speed = 1000.0
            self.maxPower = 20.0

    class Parser:
        def parse_material_library(self, path):
            assert path == "test.clb"
            return [Setting()]

    monkeypatch.setattr(services, "Lightburn", Parser)

    resolved = services.resolve_material_setting_usage(
        "test.clb", "stainless steel", ["Dark-Orange"]
    )

    assert len(resolved) == 1
    assert resolved[0]["swatch_hex"] == "#C08000"
    assert resolved[0]["swatch_name"] == "Dark-Orange"
    assert resolved[0]["material"] == "Stainless Steel"
    assert resolved[0]["description"] == "Dark-Orange"
    assert resolved[0]["setting_values"]["speed"] == 1000.0
    assert resolved[0]["setting_values"]["maxPower"] == 20.0


def test_material_usage_resolution_ignores_cut_setting_name(monkeypatch):
    class Setting:
        def __init__(self, description, cut_setting_name):
            self.materialName = "Stainless Steel"
            self.entryDesc = description
            self.name = cut_setting_name
            self.type = "Scan"
            self.subLayers = []
            self.speed = 1000.0

    class Parser:
        def parse_material_library(self, _path):
            return [
                Setting("Teal", "Teal"),
                Setting("Light-Blue", "Teal"),
            ]

    monkeypatch.setattr(services, "Lightburn", Parser)

    resolved = services.resolve_material_setting_usage(
        "test.clb", "stainless steel", ["Teal"]
    )

    assert len(resolved) == 1
    assert resolved[0]["description"] == "Teal"


def test_rasterizer_palette_initialization_has_no_retired_holographic_call():
    template = Path("templates/index.html").read_text(encoding="utf-8")
    active_template = re.sub(r"/\*.*?\*/", "", template, flags=re.DOTALL)
    assert "updateHolographicSwatchReadout(" not in active_template


def test_setting_usage_async_returns_before_recorder_finishes(monkeypatch):
    recorder_started = threading.Event()
    release_recorder = threading.Event()

    def slow_recorder(task_id, resolved_settings, library):
        recorder_started.set()
        release_recorder.wait(2)

    monkeypatch.setattr(services, "record_setting_usage", slow_recorder)
    usage_thread = services.record_setting_usage_async(
        "task-1", [{"swatch_hex": "#000000"}], {"laser_source": "test"}
    )

    assert recorder_started.wait(1)
    assert usage_thread.is_alive()
    release_recorder.set()
    usage_thread.join(1)
    assert not usage_thread.is_alive()

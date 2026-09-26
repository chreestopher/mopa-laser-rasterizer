import json
import sys
import zipfile
from pathlib import Path

import pytest
from PIL import Image
from shapely.geometry import box


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import lightburn  # noqa: E402
import vector_processing  # noqa: E402
import Material_Library  # noqa: E402


def panel_settings(**overrides):
    values = {
        "enabled": True,
        "tile_width_mm": 10,
        "tile_height_mm": 10,
        "columns": 2,
        "rows": 1,
        "gap_x_mm": 2,
        "gap_y_mm": 0,
        "edge_inset_mm": 1,
        "workbed_width_mm": 10,
        "workbed_height_mm": 14,
        "order": "row_major",
        "include_tile_ids": True,
    }
    values.update(overrides)
    return vector_processing.normalize_panel_tiling(values)


def test_panel_dimensions_include_physical_gaps():
    settings = panel_settings(rows=3, columns=4, gap_x_mm=2, gap_y_mm=3)
    assert vector_processing.panel_tiling_dimensions(settings) == (46, 36)


def test_high_resolution_plan_keeps_limit_per_panel_not_per_assembly():
    settings = panel_settings(
        tile_width_mm=100,
        tile_height_mm=80,
        workbed_width_mm=100,
        workbed_height_mm=80,
        columns=2,
        rows=1,
    )

    plan = Material_Library.high_resolution_panel_plan(settings, 0.1)

    assert plan["assembled_width_px"] == 2020
    assert plan["tile_width_px"] == 1000
    assert plan["tile_height_px"] == 800
    assert plan["oversized"] is True


def test_high_resolution_plan_rejects_an_individually_oversized_panel():
    settings = panel_settings(
        tile_width_mm=170,
        tile_height_mm=80,
        workbed_width_mm=170,
        workbed_height_mm=80,
        columns=2,
        rows=1,
    )

    with pytest.raises(ValueError, match="Each high-resolution panel"):
        Material_Library.high_resolution_panel_plan(settings, 0.1)


def test_high_resolution_plan_caps_total_work_without_lowering_axis_limit():
    settings = panel_settings(
        tile_width_mm=160,
        tile_height_mm=160,
        workbed_width_mm=160,
        workbed_height_mm=160,
        columns=4,
        rows=4,
    )

    with pytest.raises(ValueError, match="40-million"):
        Material_Library.high_resolution_panel_plan(settings, 0.1)


def test_high_resolution_panel_job_packages_bounded_parallel_children(tmp_path, monkeypatch):
    source = Image.new("RGB", (20, 10), "red")
    source_path = tmp_path / "source.png"
    source.save(source_path)
    output_path = tmp_path / "output"
    settings = panel_settings(
        tile_width_mm=4,
        tile_height_mm=4,
        workbed_width_mm=8,
        workbed_height_mm=8,
        columns=2,
        rows=1,
        gap_x_mm=1,
        gap_y_mm=0,
        edge_inset_mm=0,
    )
    plan = {
        "assembled_width_px": 9,
        "assembled_height_px": 4,
        "tile_width_px": 4,
        "tile_height_px": 4,
        "total_tile_pixels": 32,
        "oversized": True,
    }
    child_sizes = []

    class Result:
        returncode = 0
        stdout = "child complete"

    def fake_run(command, **_options):
        child = command[3:]
        with Image.open(child[0]) as tile:
            child_sizes.append(tile.size)
        archive_path = f"{child[1]}.panel-tiles.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("tile-01-r01-c01.svg", "<svg/>")
            archive.writestr("tile-01-r01-c01.svg.lbrn2", "<LightBurnProject/>")
        return Result()

    monkeypatch.setattr(Material_Library.subprocess, "run", fake_run)
    monkeypatch.setenv("RASTER_PANEL_PROCESSES", "2")
    argv = [str(source_path), str(output_path), "1", "0", "0"] + [""] * 15

    Material_Library.run_high_resolution_panel_job(argv, settings, 1, plan)

    assert sorted(child_sizes) == [(4, 4), (4, 4)]
    with zipfile.ZipFile(f"{output_path}.panel-tiles.zip") as archive:
        names = set(archive.namelist())
        assert "tile-01-r01-c01.svg.lbrn2" in names
        assert "tile-02-r01-c02.svg.lbrn2" in names
        manifest = json.loads(archive.read("panel-manifest.json"))
    assert manifest["processing_mode"] == "independent-high-resolution-panels"
    assert manifest["assembled_size_px"] == {"width": 9, "height": 4}
    assert [tile["source_origin_mm"]["x"] for tile in manifest["tiles"]] == [0, 5]


def test_panel_validation_rejects_too_many_tiles_and_impossible_inset():
    with pytest.raises(ValueError, match="at most 100 tiles"):
        panel_settings(rows=11, columns=10)
    with pytest.raises(ValueError, match="positive engravable area"):
        panel_settings(edge_inset_mm=5)
    with pytest.raises(ValueError, match="fit inside the described workbed"):
        panel_settings(tile_width_mm=11)


def test_panel_dimension_limits_allow_three_meter_tiles_and_cap_gaps():
    settings = panel_settings(
        tile_width_mm=3000,
        tile_height_mm=3000,
        workbed_width_mm=3000,
        workbed_height_mm=3000,
        gap_x_mm=1000,
        gap_y_mm=1000,
        edge_inset_mm=0,
    )

    assert settings["tile_width_mm"] == 3000
    assert settings["tile_height_mm"] == 3000
    assert settings["gap_x_mm"] == 1000
    assert settings["gap_y_mm"] == 1000
    with pytest.raises(ValueError, match="Tile width mm must be between 1 and 3000"):
        panel_settings(tile_width_mm=3000.1, workbed_width_mm=3000)
    with pytest.raises(ValueError, match="Gap x mm must be between 0 and 1000"):
        panel_settings(gap_x_mm=1000.1)


def test_legacy_workbed_values_are_treated_as_dimensions():
    values = panel_settings()
    values.pop("workbed_width_mm")
    values.pop("workbed_height_mm")
    values["origin_x_mm"] = 350
    values["origin_y_mm"] = 300

    settings = vector_processing.normalize_panel_tiling(values)

    assert settings["workbed_width_mm"] == 350
    assert settings["workbed_height_mm"] == 300


def test_panel_tiling_settings_are_disclosed_only_when_enabled():
    page = (ROOT / "serverless_web" / "index.html").read_text(encoding="utf-8")

    assert 'id="panelTilingEnabled" type="checkbox" aria-controls="panelTilingDetails" aria-expanded="false"' in page
    assert 'id="panelTilingDetails" class="layout-details" hidden' in page
    assert ".layout-details[hidden]{display:none}" in page
    assert "details.hidden=!settings.enabled" in page
    assert "toggle.setAttribute('aria-expanded',String(settings.enabled))" in page
    assert 'id="tileWidth" type="number" min="1" max="3000"' in page
    assert 'id="tileHeight" type="number" min="1" max="3000"' in page
    assert 'id="tileGapX" type="number" min="0" max="1000"' in page
    assert 'id="tileGapY" type="number" min="0" max="1000"' in page
    assert 'id="tileWorkbedWidth" type="number" min="1" max="3000"' in page
    assert 'id="tileWorkbedHeight" type="number" min="1" max="3000"' in page

    api = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")
    assert 'panel_number("tile_width_mm", 1, 3000, 100)' in api
    assert 'panel_number("tile_height_mm", 1, 3000, 100)' in api
    assert 'panel_number("gap_x_mm", 0, 1000, 0)' in api
    assert 'panel_number("gap_y_mm", 0, 1000, 0)' in api
    assert 'queue_message["worker_type"] = "high_resolution_panel"' in api
    assert 'data["high_resolution_panel"] = high_resolution_panel' in api
    assert "MAX_HIGH_RES_PANEL_PIXELS = 40_000_000" in api


def test_panel_dimensions_resize_the_complete_source_before_clipping():
    source = Image.new("RGB", (460, 640), "white")

    resized = vector_processing.resize_to_specific_height_or_width(
        source,
        width=108,
        height=170,
    )

    assert resized.size == (108, 170)


def test_serpentine_order_reverses_every_other_row():
    settings = panel_settings(rows=2, columns=3, order="serpentine")
    assert vector_processing._ordered_panel_tiles(settings) == [
        (0, 0), (0, 1), (0, 2), (1, 2), (1, 1), (1, 0),
    ]


def test_export_panel_tiles_clips_finished_geometry_and_reuses_center(tmp_path):
    vector_processing.lightburn = lightburn
    project = lightburn.Lightburn()
    project.add_layer(lightburn.FillLayer(0, "Red", 0, 20))
    target_colors = {"#FF0000": (0, 0, "Red")}
    output_path = tmp_path / "job.vector.svg"

    archive_path, assembly_path = vector_processing.export_panel_tiles(
        processed_layers={"#FF0000": box(0, 0, 22, 10)},
        target_colors=target_colors,
        black_hex="#000000",
        scale_factor=1,
        output_svg_path=str(output_path),
        lb_project_template=project,
        lightburn_note="test",
        settings=panel_settings(),
        export_lightburn=True,
    )

    assert Path(assembly_path).is_file()
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        assert {
            "panel-manifest.json",
            "panel-assembly.svg",
            "tile-01-r01-c01.svg",
            "tile-01-r01-c01.svg.lbrn2",
            "tile-02-r01-c02.svg",
            "tile-02-r01-c02.svg.lbrn2",
        } <= names
        manifest = json.loads(archive.read("panel-manifest.json"))
        assert manifest["assembled_size_mm"] == {"width": 22.0, "height": 10.0}
        assert [tile["source_origin_mm"]["x"] for tile in manifest["tiles"]] == [0.0, 12.0]
        assert all(tile["workbed_center_mm"] == {"x": 5.0, "y": 7.0} for tile in manifest["tiles"])
        assert all(tile["workbed_origin_mm"] == {"x": 0.0, "y": 2.0} for tile in manifest["tiles"])
        first_svg = archive.read("tile-01-r01-c01.svg").decode("utf-8")
        second_svg = archive.read("tile-02-r01-c02.svg").decode("utf-8")
        assert 'viewBox="0 2 10 10"' in first_svg
        assert "1.000,3.000" in first_svg
        assert "9.000,11.000" in first_svg
        assert "1.000,3.000" in second_svg
        assert "9.000,11.000" in second_svg


def test_panel_tiling_labels_workbed_dimensions_and_explains_center():
    page = (ROOT / "serverless_web" / "index.html").read_text(encoding="utf-8")

    assert "Workbed width (mm)" in page
    assert "Workbed height (mm)" in page
    assert "every generated tile is centered at half of those dimensions" in page

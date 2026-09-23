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
        "origin_x_mm": 5,
        "origin_y_mm": 7,
        "order": "row_major",
        "include_tile_ids": True,
    }
    values.update(overrides)
    return vector_processing.normalize_panel_tiling(values)


def test_panel_dimensions_include_physical_gaps():
    settings = panel_settings(rows=3, columns=4, gap_x_mm=2, gap_y_mm=3)
    assert vector_processing.panel_tiling_dimensions(settings) == (46, 36)


def test_panel_validation_rejects_too_many_tiles_and_impossible_inset():
    with pytest.raises(ValueError, match="at most 100 tiles"):
        panel_settings(rows=11, columns=10)
    with pytest.raises(ValueError, match="positive engravable area"):
        panel_settings(edge_inset_mm=5)


def test_panel_tiling_settings_are_disclosed_only_when_enabled():
    page = (ROOT / "serverless_web" / "index.html").read_text(encoding="utf-8")

    assert 'id="panelTilingEnabled" type="checkbox" aria-controls="panelTilingDetails" aria-expanded="false"' in page
    assert 'id="panelTilingDetails" class="layout-details" hidden' in page
    assert ".layout-details[hidden]{display:none}" in page
    assert "details.hidden=!settings.enabled" in page
    assert "toggle.setAttribute('aria-expanded',String(settings.enabled))" in page


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


def test_panel_tiling_labels_workbed_coordinates_as_tile_center():
    page = (ROOT / "serverless_web" / "index.html").read_text(encoding="utf-8")

    assert "Common tile center X (mm)" in page
    assert "Common tile center Y (mm)" in page
    assert "Set the common tile center to the center of your laser workbed" in page

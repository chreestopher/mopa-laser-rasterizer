import json
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from PIL import Image
from shapely.geometry import GeometryCollection, LineString, box
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
import heat_reduction
import lightburn
import Material_Library
import vector_processing as vp


@pytest.mark.parametrize("value", [1, 11, 3.5, True, "nan", "inf", "", None])
def test_project_count_validation(value):
    with pytest.raises(ValueError, match="2 to 10"):
        heat_reduction.normalize_heat_reduction({"enabled": True, "projects": value})


def test_disabled_and_valid_settings():
    assert heat_reduction.normalize_heat_reduction(None) == {"enabled": False}
    assert heat_reduction.normalize_heat_reduction({"enabled": False, "projects": "bad"}) == {"enabled": False}
    for count in range(2, 11):
        assert heat_reduction.normalize_heat_reduction(json.dumps({"enabled": True, "projects": count}))["projects"] == count


def test_filled_shapes_keep_holes_and_are_balanced_without_loss_or_overlap():
    hole_shape = box(0, 0, 3, 3).difference(box(1, 1, 2, 2))
    units = [hole_shape] + [box(5 + i * 2, 0, 6 + i * 2, 1) for i in range(24)]
    jobs = heat_reduction.distribute_layers({"red": GeometryCollection(units)}, 4)
    assigned = [unit for job in jobs for unit in heat_reduction.geometry_units(job.get("red", GeometryCollection()))]
    assert len(assigned) == len(units)
    assert all(sum(unit.equals(original) for unit in assigned) == 1 for original in units)
    assert unary_union(assigned).equals(unary_union(units))
    areas = [job["red"].area for job in jobs]
    assert areas == [8] * 4
    assert any(len(unit.interiors) == 1 for unit in assigned)


def test_krasnow_strokes_are_interleaved_over_the_whole_height():
    strokes = [LineString([(0, y), (20, y)]) for y in range(40)]
    jobs = heat_reduction.distribute_layers({"red": GeometryCollection(strokes)}, 4)
    for index, job in enumerate(jobs):
        assert [unit.coords[0][1] for unit in job["red"].geoms] == list(range(index, 40, 4))


def test_filled_krasnow_slivers_use_spatial_interleaving():
    slivers = [box(0, y, 20, y + .1) for y in range(40)]
    jobs = heat_reduction.distribute_layers({"red": GeometryCollection(slivers)}, 4, {"red"})
    for index, job in enumerate(jobs):
        assert [unit.bounds[1] for unit in job["red"].geoms] == list(range(index, 40, 4))


def project_template():
    vp.lightburn = lightburn
    project = lightburn.Lightburn()
    project.add_layer(lightburn.FillLayer(0, "Red", 0, 20))
    return project


def test_projects_reuse_bounds_and_only_tool_perimeter_is_duplicated(tmp_path):
    project = project_template()
    layers = {"#FF0000": GeometryCollection([box(i * 2, 3, i * 2 + 1, 4) for i in range(8)])}
    result = vp.export_heat_projects(
        layers, {"#FF0000": (0, 0, "Red")}, "#000000", project,
        vp._tile_svg_root(20, 10, 0, 2), str(tmp_path / "artwork"), "test",
        {"enabled": True, "projects": 4}, True,
    )
    perimeters = []
    engraving_count = 0
    for item in result["projects"]:
        svg = ET.parse(tmp_path / item["svg"]).getroot()
        assert svg.get("viewBox") == "0 2 20 10"
        lb = ET.parse(tmp_path / item["lightburn"]).getroot()
        tool = lb.find("CutSetting[@type='Tool']")
        assert tool.find("index").get("Value") == "30"
        assert tool.find("doOutput").get("Value") == "0"
        perimeter = lb.find("Shape[@CutIndex='30']")
        perimeters.append(ET.tostring(perimeter))
        engraving_count += len(lb.findall("Shape[@CutIndex='0']"))
        assert "project" in lb.find("Notes").get("Notes")
    # Shape IDs vary; dimensions, location, and tool assignment must not.
    elements = [ET.fromstring(value) for value in perimeters]
    assert all(element.get("W") == "20.0" and element.get("H") == "10.0" for element in elements)
    assert len({element.find("XForm").text for element in elements}) == 1
    assert engraving_count == 8
    assert not project.objects


def test_specialized_carrier_does_not_collide_with_alignment_tool(tmp_path):
    project = project_template()
    project.add_layer(lightburn.CutLayer(30, "Krasnow carrier", 0, 20, 1000))
    manifest = vp.export_heat_projects(
        {"#FF0000": LineString([(0, 1), (10, 1)])}, {"#FF0000": (0, 30, "Carrier")},
        "#000000", project, vp._tile_svg_root(10, 10, 0, 0), str(tmp_path / "carrier"),
        "test", {"projects": 2}, True,
    )
    root = ET.parse(tmp_path / manifest["projects"][0]["lightburn"]).getroot()
    assert root.find("CutSetting[@type='Cut']/index").get("Value") == "0"
    assert root.find("Shape[@Type='Path']").get("CutIndex") == "0"
    assert root.find("Shape[@Type='Rect']").get("CutIndex") == "30"
    assert project._layers[-1].index == 30


def test_alignment_includes_geometry_extended_beyond_the_source_canvas(tmp_path):
    manifest = vp.export_heat_projects(
        {"#FF0000": box(-2, 0, 12, 5)}, {"#FF0000": (0, 0, "Red")}, "#000000",
        project_template(), vp._tile_svg_root(10, 10, 0, 0), str(tmp_path / "extended"),
        "test", {"projects": 2}, True,
    )
    assert manifest["alignment_bounds_mm"] == [-2, 0, 14, 10]
    for job in manifest["projects"]:
        assert ET.parse(tmp_path / job["svg"]).getroot().get("viewBox") == "-2 0 14 10"


@pytest.mark.parametrize("svg_only", [False, True])
@pytest.mark.parametrize("style", ["vectors", "krasnow_grating"])
def test_complete_raster_export_produces_only_numbered_cooling_projects(tmp_path, svg_only, style):
    source = tmp_path / "source.png"
    Image.new("RGB", (12, 12), "red").save(source)
    project = project_template()
    vp.raster_to_puzzle_and_lightburn(
        str(source), str(tmp_path / "job.vector.svg"), 12, 12, project,
        {"#FF0000": (0, 0, "Red")}, scale_factor=.5,
        heat_reduction={"enabled": True, "projects": 4},
        export_lightburn=not svg_only,
        geometry_style=style,
    )
    assert not (tmp_path / "job.vector.svg.lbrn2").exists()
    with zipfile.ZipFile(tmp_path / "job.heat-reduction.zip") as archive:
        manifest = json.loads(archive.read("heat-manifest.json"))
        assert manifest["alignment_bounds_mm"] == [0, 0, 6, 6]
        assert len(manifest["projects"]) == 4
        assert sum(name.endswith(".lbrn2") for name in archive.namelist()) == (0 if svg_only else 4)


def test_worker_argument_reaches_cooling_export(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGB", (8, 8), "red").save(source)
    argv = [str(source), str(tmp_path / "worker"), ".5", "8", "0", "-", "", "Red", "cartoon", "none", "{}", "{}", "true", "{}", "false", "vectors", "{}", "", "engraved", '{"enabled":false}', '{"enabled":true,"projects":10}']
    Material_Library.main(argv)
    with zipfile.ZipFile(tmp_path / "worker.heat-reduction.zip") as archive:
        manifest = json.loads(archive.read("heat-manifest.json"))
        assert len(manifest["projects"]) == 10


def test_panel_cooling_archive_can_be_assembled_by_high_resolution_worker(tmp_path):
    project = project_template()
    settings = vp.normalize_panel_tiling({
        "enabled": True, "tile_width_mm": 10, "tile_height_mm": 10,
        "columns": 1, "rows": 1, "workbed_width_mm": 20, "workbed_height_mm": 20,
    })
    path, _ = vp.export_panel_tiles(
        {"#FF0000": box(0, 0, 10, 10)}, {"#FF0000": (0, 0, "Red")}, "#000000",
        1, str(tmp_path / "panel.vector.svg"), project, "test", settings,
        heat_reduction={"enabled": True, "projects": 4},
    )
    destination = tmp_path / "assembled"
    destination.mkdir()
    result = Material_Library._extract_single_panel_archive(path, str(destination), "tile-02-r01-c02")
    assert result["alignment_bounds_mm"] == [5, 5, 10, 10]
    assert len(list(destination.glob("*.lbrn2"))) == 4
    assert all(item["lightburn"].startswith("tile-02-r01-c02-heat-") for item in result["projects"])

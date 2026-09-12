import math

from PIL import Image, ImageDraw
from shapely.geometry import box

from lib.abstract_filters import FULL_PALETTE_FILTERS, MODULES, manifest
from lib.abstract_filters import structure_tensor_flow


TARGET_COLORS = {
    "#FF0000": ["Red", 2, "Red"],
    "#0000FF": ["Blue", 3, "Blue"],
    "#000000": ["Black", 0, "Black"],
}


def source_image():
    image = Image.new("L", (48, 32), 32)
    draw = ImageDraw.Draw(image)
    draw.ellipse((8, 4, 40, 28), fill=230)
    return image


def settings(**overrides):
    values = {
        **structure_tensor_flow.DEFAULTS,
        "_canvas_bounds": (0, 0, 48, 32),
        "_scale_factor": 0.2,
        "_angle_image": source_image(),
    }
    values.update(overrides)
    return values


def test_filter_is_registered_for_the_full_palette_pipeline():
    assert MODULES["structure_tensor_flow"] is structure_tensor_flow
    assert "structure_tensor_flow" in FULL_PALETTE_FILTERS
    assert manifest()["structure_tensor_flow"]["defaults"]["line_spacing_mm"] == 0.9
    assert manifest()["structure_tensor_flow"]["defaults"]["minimum_ribbon_width_mm"] == 0.10
    assert manifest()["structure_tensor_flow"]["defaults"]["maximum_ribbon_width_mm"] == 0.35
    assert structure_tensor_flow.USES_SOURCE_LUMINANCE is True
    assert structure_tensor_flow.PRESERVE_SOURCE_BLACK is True


def test_flow_is_deterministic_clipped_and_layer_exclusive():
    layers = {
        "#FF0000": box(0, 0, 26, 32),
        "#0000FF": box(22, 0, 48, 32),
    }
    first = structure_tensor_flow.remap_layers(layers, TARGET_COLORS, settings())
    second = structure_tensor_flow.remap_layers(layers, TARGET_COLORS, settings())
    assert first.keys() == second.keys()
    assert all(first[color].wkb == second[color].wkb for color in first)
    assert first["#FF0000"].intersection(first["#0000FF"]).area <= 1e-9
    canvas = box(0, 0, 48, 32)
    assert all(geometry.difference(canvas).area <= 1e-9 for geometry in first.values())


def test_flow_rotation_changes_the_tensor_structures():
    layers = {"#FF0000": box(0, 0, 48, 32)}
    original = structure_tensor_flow.remap_layers(
        layers, TARGET_COLORS, settings(flow_rotation=0, seed_jitter=0)
    )["#FF0000"]
    rotated = structure_tensor_flow.remap_layers(
        layers, TARGET_COLORS, settings(flow_rotation=90, seed_jitter=0)
    )["#FF0000"]
    assert original.wkb != rotated.wkb
    assert not math.isclose(original.length, rotated.length, rel_tol=1e-3)


def test_abstraction_axis_releases_strokes_from_source_boundaries():
    red_source = box(4, 4, 24, 28)
    blue_source = box(24, 4, 44, 28)
    layers = {"#FF0000": red_source, "#0000FF": blue_source}
    photorealistic = structure_tensor_flow.remap_layers(
        layers,
        TARGET_COLORS,
        settings(abstraction=0, seed_jitter=0, minimum_color_run_mm=0),
    )
    abstract = structure_tensor_flow.remap_layers(
        layers,
        TARGET_COLORS,
        settings(abstraction=1, seed_jitter=0, minimum_color_run_mm=0),
    )
    assert all(
        photorealistic[color].difference(layers[color]).area <= 1e-9
        for color in photorealistic
    )
    assert any(
        abstract[color].difference(layers[color]).area > 0.1
        for color in abstract
    )
    assert abstract["#FF0000"].intersection(abstract["#0000FF"]).area <= 1e-9


def test_line_spacing_controls_density():
    layers = {"#FF0000": box(0, 0, 48, 32)}
    dense = structure_tensor_flow.remap_layers(
        layers, TARGET_COLORS, settings(line_spacing_mm=0.5)
    )["#FF0000"]
    sparse = structure_tensor_flow.remap_layers(
        layers, TARGET_COLORS, settings(line_spacing_mm=1.5)
    )["#FF0000"]
    assert dense.area > sparse.area


def test_long_wide_ribbons_remain_broken_into_distinct_marks():
    source = box(0, 0, 48, 32)
    output = structure_tensor_flow.remap_layers(
        {"#FF0000": source},
        TARGET_COLORS,
        settings(
            abstraction=0.5,
            line_spacing_mm=0.8,
            line_length_mm=8,
            minimum_ribbon_width_mm=0.5,
            maximum_ribbon_width_mm=0.5,
            source_blur_px=2.4,
        ),
    )["#FF0000"]
    assert len(structure_tensor_flow._polygon_parts(output)) > 1
    assert output.area < source.area


def test_collision_resolution_breaks_both_ribbons_at_intersections():
    first = box(0, 0, 3, 1)
    second = box(1, -1, 2, 2)
    ribbons = [
        (first, 1, 0.5, 1, 0),
        (second, 1.5, 0.5, 1, math.pi / 2),
    ]
    accepted = structure_tensor_flow._remove_ribbon_overlaps(
        ribbons, (0, -1, 3, 2), spacing=1, maximum_width=1
    )
    assert len(accepted) == 2
    assert accepted[0][0].intersection(accepted[1][0]).area <= 1e-9
    assert accepted[0][0].distance(accepted[1][0]) > 0
    assert accepted[0][0].area < first.area
    assert accepted[1][0].area < second.area


def test_parallel_ribbons_use_priority_without_merging_boundaries():
    first = box(0, 0, 3, 1)
    second = box(2, 0, 5, 1)
    accepted = structure_tensor_flow._remove_ribbon_overlaps(
        [(first, 1, 0.5, 1, 0), (second, 4, 0.5, 1, 0)],
        (0, 0, 5, 1),
        spacing=1,
        maximum_width=1,
    )
    assert len(accepted) == 2
    assert math.isclose(accepted[0][0].area, first.area)
    assert accepted[0][0].distance(accepted[1][0]) > 0


def test_short_color_runs_merge_into_the_neighbor_with_shared_boundary():
    red_fragment = box(0, 0, 0.1, 1)
    blue_neighbor = box(0.1, 0, 2, 1)
    merged, transfers = structure_tensor_flow._merge_short_color_runs(
        {"#FF0000": red_fragment, "#0000FF": blue_neighbor},
        TARGET_COLORS,
        minimum_area=0.2,
    )
    assert transfers == 1
    assert "#FF0000" not in merged
    assert math.isclose(merged["#0000FF"].area, 2.0)


def test_shared_boundary_length_falls_back_when_geos_returns_none():
    fragment = box(0, 0, 0.1, 1)
    target = box(0.1, 0, 2, 1)

    class NullIntersectionBoundary:
        def intersection(self, _other):
            return None

    class NullBoundaryFragment:
        boundary = NullIntersectionBoundary()
        bounds = fragment.bounds

        def intersection(self, other):
            return fragment.intersection(other)

    assert structure_tensor_flow._shared_boundary_length(
        NullBoundaryFragment(), target
    ) > 0.99


def test_width_range_changes_ribbon_coverage_without_layer_overlap():
    layers = {
        "#FF0000": box(0, 0, 26, 32),
        "#0000FF": box(22, 0, 48, 32),
    }
    narrow = structure_tensor_flow.remap_layers(
        layers,
        TARGET_COLORS,
        settings(
            minimum_ribbon_width_mm=0.05,
            maximum_ribbon_width_mm=0.10,
            minimum_color_run_mm=0,
        ),
    )
    wide = structure_tensor_flow.remap_layers(
        layers,
        TARGET_COLORS,
        settings(
            minimum_ribbon_width_mm=0.30,
            maximum_ribbon_width_mm=0.60,
            minimum_color_run_mm=0,
        ),
    )
    assert sum(geometry.area for geometry in wide.values()) > sum(
        geometry.area for geometry in narrow.values()
    )
    assert wide["#FF0000"].intersection(wide["#0000FF"]).area <= 1e-9


def test_excessive_seed_grid_has_actionable_error():
    try:
        structure_tensor_flow.remap_layers(
            {"#FF0000": box(0, 0, 1000, 1000)},
            TARGET_COLORS,
            settings(
                _canvas_bounds=(0, 0, 1000, 1000),
                _angle_image=Image.new("L", (1000, 1000), 128),
                _scale_factor=1,
                line_spacing_mm=0.2,
            ),
        )
    except ValueError as error:
        assert "Increase Line Spacing MM" in str(error)
    else:
        raise AssertionError("Expected an oversized flow grid to be rejected")


def test_staging_ui_api_and_worker_expose_the_filter():
    ui = open("serverless_web/index.html", encoding="utf-8").read()
    worker = open("services.py", encoding="utf-8").read()
    api = open("serverless_api/handler.py", encoding="utf-8").read()
    matrix = open("lib/run_filter_matrix.sh", encoding="utf-8").read()
    assert 'value="abstract_structure_tensor_flow"' in ui
    assert "Photorealistic" in ui and "Abstract" in ui
    for control_name in structure_tensor_flow.DEFAULTS:
        assert control_name in ui
    assert '"structure_tensor_flow"' in worker
    assert '"structure_tensor_flow"' in api
    assert "structure_tensor_flow" in matrix

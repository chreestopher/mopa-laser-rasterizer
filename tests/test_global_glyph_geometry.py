import os
import sys
from pathlib import Path
from unittest.mock import patch

from PIL import Image
import pytest
from shapely.geometry import box


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-2")

import geometry_styles
import glyph_geometry
import vector_processing
from abstract_filters import halftone_newsprint, krasnow_grating
from services import parse_geometry_style_parameters


TARGET_COLORS = {
    "#FF0000": ["Red", 2, "Red"],
    "#000000": ["Black", 0, "Black"],
}


def glyph_parameters(**overrides):
    values = {
        "glyph_shape": "star",
        "cell_size_mm": 1,
        "minimum_glyph_ratio": .3,
        "maximum_glyph_ratio": .9,
        "non_black_glyph_density": 1,
        "tone_curve": .75,
        "contrast": 2,
        "grid_angle": 0,
        "glyph_rotation": 0,
        "seed": 9,
        "_canvas_bounds": (0, 0, 8, 4),
        "_scale_factor": 1,
        "_angle_image": Image.new("L", (8, 4), 96),
    }
    values.update(overrides)
    return values


def test_normal_vectors_are_unchanged_and_glyphs_are_deterministic():
    layers = {"#FF0000": box(0, 0, 8, 4)}
    unchanged = geometry_styles.apply(layers, TARGET_COLORS, "vectors", {}, "wave")
    first = geometry_styles.apply(layers, TARGET_COLORS, "glyphs", glyph_parameters(), "wave")
    second = geometry_styles.apply(layers, TARGET_COLORS, "glyphs", glyph_parameters(), "wave")

    assert unchanged is layers
    assert 0 < first["#FF0000"].area < layers["#FF0000"].area
    assert first["#FF0000"].wkb == second["#FF0000"].wkb


def test_mixed_global_glyphs_change_repeatably_with_seed():
    layers = {"#FF0000": box(0, 0, 8, 4)}
    first = geometry_styles.apply(
        layers, TARGET_COLORS, "glyphs", glyph_parameters(glyph_shape="mixed", seed=11), "ripple"
    )["#FF0000"]
    second = geometry_styles.apply(
        layers, TARGET_COLORS, "glyphs", glyph_parameters(glyph_shape="mixed", seed=12), "ripple"
    )["#FF0000"]

    assert first.wkb != second.wkb


def test_positive_and_invert_fill_outputs_never_overlap_layers():
    layers = {
        "#FF0000": box(0, 0, 6, 4),
        "#000000": box(4, 0, 8, 4),
    }
    for invert_fill in (0, 1):
        output = geometry_styles.apply(
            layers,
            TARGET_COLORS,
            "glyphs",
            glyph_parameters(
                glyph_shape="heart",
                invert_fill=invert_fill,
                black_only=0,
                cell_size_mm=1,
                minimum_glyph_ratio=.3,
                maximum_glyph_ratio=.8,
            ),
            "wave",
        )
        assert output["#FF0000"].intersection(output["#000000"]).area <= 1e-9
        if invert_fill:
            assert output["#FF0000"].difference(layers["#FF0000"]).area <= 1e-9
            assert output["#000000"].difference(layers["#000000"]).area <= 1e-9


def test_invert_fill_keeps_vectors_and_creates_layer_local_glyph_holes():
    source = box(0, 0, 8, 4)
    output = geometry_styles.apply(
        {"#FF0000": source},
        {"#FF0000": TARGET_COLORS["#FF0000"]},
        "glyphs",
        glyph_parameters(glyph_shape="star", invert_fill=1, black_only=0),
        "ripple",
    )["#FF0000"]
    assert 0 < output.area < source.area
    assert output.difference(source).area <= 1e-9


def test_invert_fill_rejects_black_only_mode():
    try:
        geometry_styles.normalize(
            "glyphs", {"invert_fill": 1, "black_only": 1}, "wave"
        )
    except ValueError as error:
        assert "cannot be combined" in str(error)
    else:
        raise AssertionError("Expected Invert Fill plus Black Only to be rejected")


def test_overlap_export_gate_rejects_geometry_owned_by_multiple_layers():
    try:
        halftone_newsprint._assert_exclusive_layers({
            "#FF0000": box(0, 0, 2, 2),
            "#000000": box(1, 1, 3, 3),
        })
    except ValueError as error:
        assert "overlap validation failed" in str(error)
    else:
        raise AssertionError("Expected overlapping LightBurn layers to be rejected")


def test_glyph_style_preserves_source_black_and_rejects_specialized_filters():
    assert geometry_styles.preserves_source_black("glyphs")
    assert geometry_styles.uses_source_luminance("glyphs")
    for name in geometry_styles.SPECIALIZED_FILTERS:
        try:
            geometry_styles.normalize("glyphs", {}, name)
        except ValueError as error:
            assert "not available" in str(error)
        else:
            raise AssertionError(f"Expected {name} to reject the global glyph style")


def test_krasnow_geometry_style_is_deterministic_and_uses_shared_engine():
    layers = {"#FF0000": box(0, 0, 8, 4)}
    parameters = {
        "cell_shape": "square",
        "preserve_black": 1,
        "patch_size_mm": 2,
        "line_spacing_mm": .5,
        "hue_line_spacing_minimum_mm": .5,
        "hue_line_spacing_maximum_mm": .5,
        "angle_min": 0,
        "angle_max": 0,
        "_canvas_bounds": (0, 0, 8, 4),
        "_scale_factor": 1,
        "_angle_image": Image.new("L", (8, 4), 96),
    }

    first = geometry_styles.apply(
        layers, TARGET_COLORS, "krasnow_grating", parameters, "wave"
    )
    second = geometry_styles.apply(
        layers, TARGET_COLORS, "krasnow_grating", parameters, "wave"
    )

    assert geometry_styles.module_for_style("krasnow_grating") is krasnow_grating
    assert geometry_styles.uses_source_luminance("krasnow_grating")
    assert geometry_styles.preserves_source_black("krasnow_grating", parameters)
    assert first["#FF0000"].length > 0
    assert first["#FF0000"].wkb == second["#FF0000"].wkb
    assert first["#FF0000"].difference(layers["#FF0000"]).length <= 1e-9


def test_by_swatch_routing_applies_one_geometry_style_per_layer():
    target_colors = {
        "#FF0000": [0, 2, "Red"],
        "#00E000": [120, 3, "Green"],
        "#000000": [0, 0, "Black"],
    }
    layers = {
        "#FF0000": box(0, 0, 4, 4),
        "#00E000": box(4, 0, 8, 4),
        "#000000": box(0, 4, 8, 6),
    }
    parameters = {
        "assignments": {
            "#FF0000": "glyphs",
            "#00E000": "krasnow_grating",
            "#000000": "krasnow_grating",
        },
        "glyphs": glyph_parameters(glyph_shape="star"),
        "krasnow_grating": {
            "cell_shape": "square",
            "patch_size_mm": 2,
            "line_spacing_mm": .5,
            "hue_line_spacing_minimum_mm": .5,
            "hue_line_spacing_maximum_mm": .5,
            "angle_min": 0,
            "angle_max": 0,
        },
        "_canvas_bounds": (0, 0, 8, 6),
        "_scale_factor": 1,
        "_angle_image": Image.new("L", (8, 6), 96),
    }

    style, normalized = geometry_styles.normalize(
        "by_swatch", parameters, "wave"
    )
    output = geometry_styles.apply(
        layers, target_colors, style, normalized, "wave"
    )

    assert normalized["assignments"]["#000000"] == "vectors"
    assert 0 < output["#FF0000"].area < layers["#FF0000"].area
    assert output["#00E000"].length > 0
    assert output["#000000"].equals(layers["#000000"])
    items = list(output.items())
    for index, (_, left) in enumerate(items):
        for _, right in items[index + 1:]:
            assert left.intersection(right).area <= 1e-9


def test_by_swatch_parser_accepts_nested_renderer_settings():
    parsed = parse_geometry_style_parameters({
        "assignments": {
            "#ff0000": "glyphs",
            "#00e000": "krasnow_grating",
            "#000000": "krasnow_grating",
        },
        "glyphs": {"glyph_shape": "star", "cell_size_mm": .6},
        "krasnow_grating": {"cell_shape": "hexagon", "patch_size_mm": .4},
    })

    assert parsed["assignments"] == {
        "#FF0000": "glyphs",
        "#00E000": "krasnow_grating",
        "#000000": "vectors",
    }
    assert parsed["glyphs"]["glyph_shape"] == "star"
    assert parsed["krasnow_grating"]["cell_shape"] == "hexagon"


def test_by_swatch_does_not_force_the_dedicated_krasnow_black_mask():
    parsed = parse_geometry_style_parameters({
        "assignments": {
            "#000000": "krasnow_grating",
            "#0000FF": "krasnow_grating",
        },
        "krasnow_grating": {"preserve_black": 0},
    })

    assert parsed["assignments"]["#000000"] == "vectors"
    assert parsed["krasnow_grating"]["preserve_black"] == 0


def test_by_swatch_omits_settings_for_unused_geometry_renderers():
    parsed = parse_geometry_style_parameters({
        "assignments": {
            "#FF0000": "krasnow_grating",
        },
        "glyphs": {"glyph_shape": "star", "cell_size_mm": .6},
        "krasnow_grating": {"cell_shape": "hexagon", "patch_size_mm": .4},
    })

    assert "glyphs" not in parsed
    assert parsed["krasnow_grating"]["cell_shape"] == "hexagon"


def test_by_swatch_krasnow_quantizes_black_normally_without_darkness_reservation(
    tmp_path,
):
    image_path = tmp_path / "blue-and-black.png"
    image = Image.new("RGB", (2, 1))
    image.putdata([(0, 0, 255), (0, 0, 0)])
    image.save(image_path)
    captured = {}

    with patch.object(
        vector_processing,
        "load_resized_source_black_cutoff_mask",
        side_effect=AssertionError("mixed routing must not reserve dark pixels"),
    ), patch.object(
        vector_processing,
        "export_processed_layers",
        side_effect=lambda **kwargs: captured.update(kwargs),
    ), patch.object(vector_processing, "save_vector_output"):
        vector_processing.raster_to_puzzle_and_lightburn(
            raster_image_path=image_path,
            output_svg_path=str(tmp_path / "mixed.svg"),
            new_height=0,
            new_width=2,
            lb_project_instance=object(),
            TARGET_COLORS={
                "#000000": (0, 0, "Black"),
                "#0000FF": (240, 1, "Blue"),
            },
            scale_factor=1,
            image_preset="cartoon",
            abstract_filter="none",
            export_lightburn=False,
            geometry_style="by_swatch",
            geometry_style_parameters={
                "assignments": {
                    "#000000": "vectors",
                    "#0000FF": "krasnow_grating",
                },
                "krasnow_grating": {
                    "preserve_black": 1,
                    "patch_size_mm": 1,
                    "line_spacing_mm": .25,
                    "hue_line_spacing_minimum_mm": .25,
                    "hue_line_spacing_maximum_mm": .25,
                    "angle_min": 0,
                    "angle_max": 0,
                },
            },
        )

    layers = captured["processed_layers"]
    assert layers["#000000"].area == pytest.approx(1, abs=1e-8)
    assert not layers["#0000FF"].is_empty
    assert layers["#000000"].intersection(layers["#0000FF"]).length <= 1e-9


def test_krasnow_geometry_style_does_not_override_palette_quantization():
    settings = dict(vector_processing.PHOTO_TYPE_PRESETS["cartoon"])
    settings.update(
        geometry_styles.module_for_style("krasnow_grating").VECTOR_DEFAULTS
    )
    settings.update(
        geometry_styles.vector_settings_for_style("krasnow_grating", {})
    )

    assert vector_processing.PHOTO_TYPE_PRESETS["cartoon"]["quantize_colors"] is None
    assert settings["quantize_colors"] is None
    assert "posterize_colors" not in krasnow_grating.DEFAULTS
    assert all(name != "posterize_colors" for name, *_ in krasnow_grating.CONTROLS)
    assert geometry_styles.vector_settings_for_style("krasnow_grating", {}) == {}


def test_krasnow_geometry_style_rejects_specialized_filters():
    for name in geometry_styles.SPECIALIZED_FILTERS:
        try:
            geometry_styles.normalize("krasnow_grating", {}, name)
        except ValueError as error:
            assert "not available" in str(error)
        else:
            raise AssertionError(
                f"Expected {name} to reject the Krasnow Grating geometry style"
            )


def test_krasnow_geometry_style_resolves_filter_overlaps_before_grating():
    layers = {
        "#FF0000": box(0, 0, 6, 4),
        "#000000": box(3, 0, 8, 4),
    }
    exclusive = geometry_styles._exclusive_source_layers(
        layers, TARGET_COLORS, (0, 0, 8, 4)
    )

    assert exclusive["#FF0000"].intersection(exclusive["#000000"]).area <= 1e-9
    assert exclusive["#000000"].area == 20
    assert exclusive["#FF0000"].area == 12

    parameters = {
        "cell_shape": "hexagon",
        "preserve_black": 0,
        "patch_size_mm": 2,
        "line_spacing_mm": .5,
        "hue_line_spacing_minimum_mm": .5,
        "hue_line_spacing_maximum_mm": .5,
        "angle_min": 45,
        "angle_max": 45,
        "_canvas_bounds": (0, 0, 8, 4),
        "_scale_factor": 1,
        "_angle_image": Image.new("L", (8, 4), 180),
    }
    output = geometry_styles.apply(
        layers, TARGET_COLORS, "krasnow_grating", parameters, "glitch"
    )

    assert output
    assert sum(geometry.length for geometry in output.values()) > 0
    output_items = list(output.items())
    for index, (_, left) in enumerate(output_items):
        for _, right in output_items[index + 1:]:
            assert left.intersection(right).length <= 1e-9
    assert not geometry_styles.preserves_source_black(
        "krasnow_grating", parameters
    )


def test_geometry_parameter_parser_accepts_only_supported_controls():
    assert parse_geometry_style_parameters({
        "glyph_shape": "mixed", "cell_size_mm": .6, "invert": False,
        "invert_fill": 1, "black_only": 0, "seed": 7,
    }) == {
        "glyph_shape": "mixed", "cell_size_mm": .6, "invert": 0,
        "invert_fill": 1, "black_only": 0, "seed": 7,
    }
    assert parse_geometry_style_parameters({
        "cell_shape": "hexagon", "preserve_black": False,
        "fauxlogram_gradient_scope": "each_shape",
        "fauxlogram_gradient_direction": "center_to_edge",
        "patch_size_mm": .4, "line_spacing_mm": .06,
        "hue_line_spacing_minimum_mm": .05,
        "hue_line_spacing_maximum_mm": .07,
        "speed_spread": 1,
    }) == {
        "cell_shape": "hexagon", "preserve_black": 0,
        "fauxlogram_gradient_scope": "each_shape",
        "fauxlogram_gradient_direction": "center_to_edge",
        "patch_size_mm": .4, "line_spacing_mm": .06,
        "hue_line_spacing_minimum_mm": .05,
        "hue_line_spacing_maximum_mm": .07,
        "speed_spread": 1,
    }
    try:
        parse_geometry_style_parameters({"unknown": 1})
    except ValueError as error:
        assert "invalid" in str(error)
    else:
        raise AssertionError("Expected an unknown geometry parameter to be rejected")


def test_fauxlogram_gradient_directions_cover_axes_and_radial_space():
    bounds = (0, 0, 10, 20)
    position = krasnow_grating._gradient_position

    assert position(5, 0, bounds, {"fauxlogram_gradient_direction": "top_to_bottom"}) == 0
    assert position(5, 20, bounds, {"fauxlogram_gradient_direction": "top_to_bottom"}) == 1
    assert position(5, 0, bounds, {"fauxlogram_gradient_direction": "bottom_to_top"}) == 1
    assert position(0, 10, bounds, {"fauxlogram_gradient_direction": "left_to_right"}) == 0
    assert position(10, 10, bounds, {"fauxlogram_gradient_direction": "right_to_left"}) == 0
    assert position(5, 10, bounds, {"fauxlogram_gradient_direction": "center_to_edge"}) == 0
    assert position(5, 10, bounds, {"fauxlogram_gradient_direction": "edge_to_center"}) == 1
    assert position(5, 0, bounds, {"fauxlogram_gradient_direction": "center_to_edge"}) == 1
    assert position(0, 10, bounds, {"fauxlogram_gradient_direction": "center_to_edge"}) == 1
    assert position(0, 0, bounds, {"fauxlogram_gradient_direction": "center_to_edge"}) == 1


def test_each_shape_fauxlogram_gradient_restarts_for_disconnected_regions():
    layers = {"#808080": box(0, 0, 4, 2).union(box(0, 8, 4, 10))}
    colors = {
        "#111111": [0, 1, "Carrier 1"],
        "#444444": [0, 2, "Carrier 2"],
        "#888888": [0, 3, "Carrier 3"],
        "#DDDDDD": [0, 4, "Carrier 4"],
    }
    base = {
        "preserve_black": 0,
        "patch_size_mm": 1,
        "line_spacing_mm": .5,
        "gradient_top": 0,
        "gradient_bottom": 255,
        "gradient_curve": 1,
        "fauxlogram_gradient_direction": "top_to_bottom",
        "angle_min": 0,
        "angle_max": 0,
        "_canvas_bounds": (0, 0, 4, 10),
        "_scale_factor": 1,
    }
    artwork = krasnow_grating.remap_layers(
        layers, colors, {**base, "fauxlogram_gradient_scope": "entire_artwork"}
    )
    shapes = krasnow_grating.remap_layers(
        layers, colors, {**base, "fauxlogram_gradient_scope": "each_shape"}
    )

    assert artwork["#111111"].bounds[3] <= 2
    assert artwork["#DDDDDD"].bounds[1] >= 8
    assert shapes["#111111"].bounds[3] > 8
    assert shapes["#888888"].bounds[1] < 2
    assert shapes["#888888"].bounds[3] > 8


def test_retired_geometry_posterize_control_is_ignored_for_cached_pages():
    assert parse_geometry_style_parameters({
        "cell_shape": "triangle",
        "posterize_colors": 12,
        "patch_size_mm": 1.2,
    }) == {
        "cell_shape": "triangle",
        "patch_size_mm": 1.2,
    }
    _, normalized = geometry_styles.normalize(
        "krasnow_grating",
        {"posterize_colors": 12, "patch_size_mm": 1.2},
        "spiral",
    )
    assert normalized["patch_size_mm"] == 1.2
    assert "posterize_colors" not in normalized


def test_global_glyphs_include_every_krasnow_shape_without_removing_existing_shapes():
    original_shapes = {
        "circle", "square", "diamond", "triangle", "hexagon", "octagon",
        "star", "cross", "bar", "mixed",
    }
    assert original_shapes <= glyph_geometry.GLYPH_SHAPES
    assert set(krasnow_grating.CELL_SHAPES) <= glyph_geometry.GLYPH_SHAPES
    for shape in krasnow_grating.CELL_SHAPES:
        assert parse_geometry_style_parameters({"glyph_shape": shape}) == {
            "glyph_shape": shape,
        }


def test_krasnow_icon_glyphs_use_their_tighter_staggered_row_spacing():
    assert krasnow_grating.solid_glyph_row_step("skull") == .8
    assert krasnow_grating.solid_glyph_row_step("bat") == .7
    assert krasnow_grating.solid_glyph_row_step("puzzle_piece") is None


def test_staging_ui_exposes_an_independent_compatible_geometry_section():
    page = (ROOT / "serverless_web" / "index.html").read_text(encoding="utf-8")
    assert 'id="geometryStyleSection"' in page
    assert '<option value="vectors">Normal Vectors</option><option value="glyphs">Glyphs</option><option value="krasnow_grating">Krasnow Grating</option><option value="by_swatch">Choose by swatch</option>' in page
    assert "SPECIALIZED_GEOMETRY_PRESETS" in page
    assert "geometry_style:effectiveGeometryStyle()" in page
    assert "geometry_style_parameters:JSON.stringify(geometryStyleParameters())" in page
    assert "if(used.has('glyphs'))parameters.glyphs=" in page
    assert "if(used.has('krasnow_grating'))parameters.krasnow_grating=krasnowGeometryValues()" in page
    assert "['invert_fill',false]" in page
    assert "syncGeometryToggleCompatibility" in page
    assert "Every output layer is made mutually exclusive before export." in page
    assert "const KRASNOW_GEOMETRY={...PRESETS.abstract_krasnow_grating" in page
    assert "fauxlogram_gradient_scope" in page
    assert "fauxlogram_gradient_direction" in page
    assert "Fauxlogram Gradient Start" in page
    assert "Fauxlogram Gradient End" in page
    assert 'id="geometryRoutingGrid"' in page
    assert 'data-route-bulk="glyphs"' in page
    assert 'data-route-bulk="krasnow_grating"' in page
    assert "posterize_colors" not in page
    assert "This requires a Fauxlographic Cut Setting" in page
    for value, label in (
        ("skull", "Skull"), ("heart", "Heart"),
        ("space_invader", "Space Invader"), ("ghost", "Ghost"),
        ("bat", "Bat"), ("alien_head", "Alien Head"),
        ("paw_print", "Paw Print"), ("fish_scale", "Fish Scale"),
        ("puzzle_piece", "Puzzle Piece"),
    ):
        assert f"['{value}','{label}']" in page


def test_serverless_api_discards_retired_posterize_from_cached_submissions():
    handler = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")
    assert 'geometry_parameters.pop("posterize_colors", None)' in handler


def _flow_settings(scope="combined_region", guide_type="linear"):
    settings = {
        **krasnow_grating.DEFAULTS,
        "fauxlogram_flow": {
            "enabled": True,
            "regions": [{
                "name": "Shared islands", "scope": scope,
                "guide_type": guide_type, "orientation": "perpendicular",
                "start": [.1, .5], "end": [.9, .5],
                "gradient_start": 20, "gradient_end": 220, "curve": 1,
                "fixed_angle": 0, "angle_offset": 0, "reverse": False,
            }],
            "strokes": [
                {"region": 0, "erase": False, "width": .2,
                 "points": [[.1, .5], [.35, .5]]},
                {"region": 0, "erase": False, "width": .2,
                 "points": [[.65, .5], [.9, .5]]},
            ],
        },
    }
    settings["_compiled_fauxlogram_flow"] = (
        krasnow_grating._prepare_fauxlogram_flow(settings)
    )
    return settings


def test_fauxlogram_flow_combines_disconnected_strokes_into_one_gradient():
    settings = _flow_settings("combined_region")
    first = krasnow_grating._painted_flow_controls(20, 50, (0, 0, 100, 100), settings)
    second = krasnow_grating._painted_flow_controls(80, 50, (0, 0, 100, 100), settings)
    assert first is not None and second is not None
    assert first[0] < second[0]
    assert first[1] == second[1] == 90


def test_fauxlogram_flow_each_shape_restarts_for_disconnected_strokes():
    settings = _flow_settings("each_shape")
    first = krasnow_grating._painted_flow_controls(20, 50, (0, 0, 100, 100), settings)
    second = krasnow_grating._painted_flow_controls(75, 50, (0, 0, 100, 100), settings)
    assert first is not None and second is not None
    assert abs(first[0] - second[0]) < 1e-9


def test_fauxlogram_flow_does_not_affect_unpainted_cells():
    settings = _flow_settings()
    assert krasnow_grating._painted_flow_controls(
        50, 10, (0, 0, 100, 100), settings
    ) is None


def test_staging_ui_exposes_fauxlogram_flow_painter():
    page = (ROOT / "serverless_web" / "index.html").read_text(encoding="utf-8")
    assert 'id="openFlowPainter"' in page
    assert 'id="flowCanvas"' in page
    assert "values.fauxlogram_flow=structuredClone(fauxlogramFlow)" in page
    assert "Every Krasnow cell still belongs to one source layer and at most one painted region" in page
    assert "function resizeFlowCanvas()" in page
    assert "availableWidth/flowBitmap.width,availableHeight/flowBitmap.height" in page
    assert "Math.min(1,960/flowBitmap.width,680/flowBitmap.height)" not in page

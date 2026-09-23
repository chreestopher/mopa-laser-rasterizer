import ast
import base64
import math
import os
import sys
from pathlib import Path
from unittest.mock import patch

from PIL import Image
import numpy as np
import pytest
from shapely.geometry import box


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-2")

import geometry_styles
import glyph_geometry
from custom_shape import decode_grayscale_mask, mask_to_unit_geometry, svg_to_unit_geometry
import vector_processing
from abstract_filters import halftone_newsprint, krasnow_grating
from services import parse_geometry_style_parameters


TARGET_COLORS = {
    "#FF0000": ["Red", 2, "Red"],
    "#000000": ["Black", 0, "Black"],
}

CUSTOM_SVG = {
    "name": "diamond.svg",
    "svg": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<path d="M50 4 L96 50 L50 96 L4 50 Z"/></svg>'
    ),
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
        "tight_pack_geometry": True,
        "invert_fill": 1, "black_only": 0, "seed": 7,
    }) == {
        "glyph_shape": "mixed", "cell_size_mm": .6, "invert": 0,
        "tight_pack_geometry": 1,
        "invert_fill": 1, "black_only": 0, "seed": 7,
    }
    assert parse_geometry_style_parameters({
        "cell_shape": "hexagon", "preserve_black": False,
        "tight_pack_geometry": "true",
        "grating_render_mode": "fill",
        "fauxlogram_gradient_scope": "each_shape",
        "fauxlogram_gradient_direction": "center_to_edge",
        "patch_size_mm": .4, "line_spacing_mm": .06,
        "hue_line_spacing_minimum_mm": .05,
        "hue_line_spacing_maximum_mm": .07,
        "speed_spread": 1,
    }) == {
        "cell_shape": "hexagon", "preserve_black": 0,
        "tight_pack_geometry": 1,
        "grating_render_mode": "fill",
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


def test_custom_svg_geometry_is_validated_and_preserved():
    assert parse_geometry_style_parameters({
        "glyph_shape": "custom",
        "custom_glyph_svg": CUSTOM_SVG,
        "custom_glyph_padding": .08,
        "tight_pack_geometry": 0,
    }) == {
        "glyph_shape": "custom",
        "custom_glyph_svg": CUSTOM_SVG,
        "custom_glyph_padding": .08,
        "tight_pack_geometry": 0,
    }
    assert parse_geometry_style_parameters({
        "cell_shape": "custom",
        "custom_cell_svg": CUSTOM_SVG,
        "custom_cell_padding": .04,
        "tight_pack_geometry": 1,
    }) == {
        "cell_shape": "custom",
        "custom_cell_svg": CUSTOM_SVG,
        "custom_cell_padding": .04,
        "tight_pack_geometry": 1,
    }

    with pytest.raises(ValueError, match="Upload a custom cell SVG"):
        parse_geometry_style_parameters({"cell_shape": "custom"})
    with pytest.raises(ValueError, match="embedded or external|couldn't be used"):
        parse_geometry_style_parameters({
            "cell_shape": "custom",
            "custom_cell_svg": {
                "name": "unsafe.svg",
                "svg": '<svg><script>alert(1)</script><path d="M0 0Z"/></svg>',
            },
        })


def test_custom_svg_preserves_closed_shape_and_hole():
    geometry = svg_to_unit_geometry({
        "name": "ring.svg",
        "svg": (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            '<path d="M5 5 H95 V95 H5 Z M30 30 H70 V70 H30 Z"/></svg>'
        ),
    }, padding=0)

    assert geometry.area == pytest.approx(1 - (40 / 90) ** 2, abs=1e-6)
    assert not geometry.contains(geometry.centroid)
    assert geometry.bounds == pytest.approx((-.5, -.5, .5, .5))


def test_custom_svg_renders_as_glyph_and_krasnow_cell():
    layers = {"#FF0000": box(0, 0, 4, 4)}
    glyph = glyph_geometry.remap_layers(
        layers,
        {"#FF0000": TARGET_COLORS["#FF0000"]},
        glyph_parameters(
            glyph_shape="custom",
            custom_glyph_svg=CUSTOM_SVG,
            cell_size_mm=1,
            grid_angle=0,
        ),
    )
    assert 0 < glyph["#FF0000"].area < layers["#FF0000"].area

    cells = krasnow_grating._tessellated_cells(
        (0, 0, 4, 4),
        1,
        "custom",
        tight_pack=True,
        custom_template=svg_to_unit_geometry(CUSTOM_SVG),
    )
    assert cells
    canvas = box(0, 0, 4, 4)
    assert all(cell.intersection(canvas).area > 0 for _, cell in cells)


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
    for shape in set(krasnow_grating.CELL_SHAPES) - {"custom"}:
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
    assert "['grating_render_mode','line'" in page
    assert "LightBurn Fill (Experimental)" in page
    assert "fauxlogram_gradient_scope" in page
    assert "fauxlogram_gradient_direction" in page
    assert "Fauxlogram Gradient Start" in page
    assert "Fauxlogram Gradient End" in page
    assert "['custom','Custom SVG']" in page
    assert 'accept=".svg,image/svg+xml,image/png,image/jpeg,image/webp"' in page
    assert 'data-custom-cell-file' in page
    assert "values.custom_cell_svg=structuredClone(customCellSvg)" in page
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


def test_serverless_job_api_accepts_tight_pack_checkbox_values():
    handler_path = ROOT / "serverless_api" / "handler.py"
    tree = ast.parse(handler_path.read_text(encoding="utf-8"))
    submit_job = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "submit_job"
    )
    toggle_assignment = next(
        node for node in ast.walk(submit_job)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "toggle_geometry_parameters"
            for target in node.targets
        )
    )

    assert "tight_pack_geometry" in ast.literal_eval(toggle_assignment.value)


def test_glyph_size_source_accepts_only_supported_modes():
    for source in ("source_brightness", "seeded_variation"):
        assert parse_geometry_style_parameters({"glyph_size_source": source}) == {
            "glyph_size_source": source
        }

    with pytest.raises(ValueError, match="glyph_size_source"):
        parse_geometry_style_parameters({"glyph_size_source": "palette_color"})


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
    assert "Add painted region" in page
    assert "Add image-mask region" in page
    assert "function resizeFlowCanvas()" in page
    assert "availableWidth/flowBitmap.width,availableHeight/flowBitmap.height" in page
    assert "Math.min(1,960/flowBitmap.width,680/flowBitmap.height)" not in page


def _compact_mask(values):
    values = np.asarray(values, dtype=np.uint8)
    return {
        "width": values.shape[1],
        "height": values.shape[0],
        "data": base64.b64encode(values.tobytes()).decode("ascii"),
    }


def test_custom_glyph_mask_decodes_and_traces_a_normalized_shape():
    values = np.zeros((16, 16), dtype=np.uint8)
    values[2:14, 6:10] = 255
    values[6:10, 2:14] = 255
    spec = _compact_mask(values)

    assert np.array_equal(decode_grayscale_mask(spec), values)
    geometry = mask_to_unit_geometry(spec, threshold=.5, padding=.05)

    assert not geometry.is_empty
    assert max(geometry.bounds[2] - geometry.bounds[0], geometry.bounds[3] - geometry.bounds[1]) <= .91
    assert geometry.area < .5


def test_custom_glyph_geometry_renders_uploaded_silhouette():
    values = np.zeros((16, 16), dtype=np.uint8)
    values[2:14, 6:10] = 255
    values[6:10, 2:14] = 255
    rendered = glyph_geometry.remap_layers(
        {"#FF0000": box(0, 0, 3, 3)},
        TARGET_COLORS,
        glyph_parameters(
            glyph_shape="custom",
            custom_glyph_mask=_compact_mask(values),
            custom_glyph_threshold=.5,
            custom_glyph_padding=.05,
        ),
    )

    assert "#FF0000" in rendered
    assert not rendered["#FF0000"].is_empty


def test_geometry_parameter_parser_preserves_custom_glyph_mask():
    values = np.zeros((16, 16), dtype=np.uint8)
    values[3:13, 3:13] = 255
    mask = _compact_mask(values)

    parsed = parse_geometry_style_parameters({
        "glyph_shape": "custom",
        "custom_glyph_mask": mask,
        "custom_glyph_threshold": .4,
        "custom_glyph_padding": .08,
        "custom_glyph_invert": 0,
    })

    assert parsed["custom_glyph_mask"] == mask
    assert parsed["glyph_shape"] == "custom"


def test_invalid_custom_glyph_mask_explains_how_to_replace_it():
    with pytest.raises(ValueError, match="The custom glyph image couldn't be used") as error:
        parse_geometry_style_parameters({"custom_glyph_mask": {}})

    assert "PNG, JPEG, or WebP" in str(error.value)


def test_invalid_flow_region_mask_explains_how_to_replace_it():
    with pytest.raises(ValueError, match="Fauxlogram Flow Painter region 1's image mask couldn't be used") as error:
        parse_geometry_style_parameters({
            "fauxlogram_flow": {
                "regions": [{"region_type": "image_mask", "mask": {}}],
                "strokes": [],
            },
        })

    assert "Remove the mask" in str(error.value)


def test_fauxlogram_flow_accepts_a_mask_without_painted_strokes():
    values = np.zeros((16, 16), dtype=np.uint8)
    values[:, :8] = 255
    settings = {
        **krasnow_grating.DEFAULTS,
        "fauxlogram_flow": {
            "enabled": True,
            "regions": [{
                "name": "Masked", "region_type": "image_mask", "scope": "combined_region",
                "guide_type": "linear", "orientation": "parallel",
                "start": [.1, .5], "end": [.9, .5],
                "gradient_start": 20, "gradient_end": 220, "curve": 1,
                "fixed_angle": 0, "angle_offset": 0, "reverse": False,
                "mask": _compact_mask(values),
                "mask_mode": "silhouette",
                "mask_threshold": .5,
            }],
            "strokes": [],
        },
    }
    settings["_compiled_fauxlogram_flow"] = krasnow_grating._prepare_fauxlogram_flow(settings)

    assert krasnow_grating._painted_flow_controls(20, 50, (0, 0, 100, 100), settings) is not None
    assert krasnow_grating._painted_flow_controls(80, 50, (0, 0, 100, 100), settings) is None


def test_grayscale_flow_mask_supplies_gradient_and_direction_without_painting():
    values = np.tile(np.linspace(0, 255, 32, dtype=np.uint8)[:, None], (1, 32))
    settings = {
        **krasnow_grating.DEFAULTS,
        "fauxlogram_flow": {
            "enabled": True,
            "regions": [{
                "name": "Masked", "scope": "combined_region",
                "guide_type": "linear", "orientation": "parallel",
                "start": [.1, .5], "end": [.9, .5],
                "gradient_start": 20, "gradient_end": 220, "curve": 1,
                "fixed_angle": 0, "angle_offset": 0, "reverse": False,
                "mask": _compact_mask(values), "mask_mode": "grayscale",
                "mask_threshold": .1,
            }],
            "strokes": [],
        },
    }
    settings["_compiled_fauxlogram_flow"] = krasnow_grating._prepare_fauxlogram_flow(settings)

    upper = krasnow_grating._painted_flow_controls(50, 25, (0, 0, 100, 100), settings)
    lower = krasnow_grating._painted_flow_controls(50, 75, (0, 0, 100, 100), settings)
    assert upper is not None and lower is not None
    assert upper[0] < lower[0]
    assert upper[1] == pytest.approx(90)
    assert lower[1] == pytest.approx(90)


def test_image_mask_region_flat_area_does_not_inherit_guide_direction():
    values = np.zeros((32, 32), dtype=np.uint8)
    values[4:28, 4:28] = 180
    region = {
        "name": "Image mask", "region_type": "image_mask",
        "scope": "combined_region", "guide_type": "linear",
        "orientation": "parallel", "start": [.1, .5], "end": [.9, .5],
        "gradient_start": 20, "gradient_end": 220, "curve": 1,
        "fixed_angle": 35, "angle_offset": 0, "reverse": False,
        "mask": _compact_mask(values), "mask_mode": "grayscale",
        "mask_threshold": .1,
    }
    settings = {
        **krasnow_grating.DEFAULTS,
        "fauxlogram_flow": {"enabled": True, "regions": [region], "strokes": []},
    }
    settings["_compiled_fauxlogram_flow"] = krasnow_grating._prepare_fauxlogram_flow(settings)
    horizontal = krasnow_grating._painted_flow_controls(50, 50, (0, 0, 100, 100), settings)
    region["start"], region["end"] = [.5, .1], [.5, .9]
    vertical = krasnow_grating._painted_flow_controls(50, 50, (0, 0, 100, 100), settings)
    assert horizontal is not None and vertical is not None
    assert horizontal == pytest.approx(vertical)
    assert horizontal[1] == pytest.approx(35)


def test_separate_image_mask_regions_keep_independent_settings():
    left_mask = np.zeros((32, 32), dtype=np.uint8)
    right_mask = np.zeros((32, 32), dtype=np.uint8)
    left_mask[4:28, 2:14] = 200
    right_mask[4:28, 18:30] = 200
    regions = []
    for name, mask, start, angle in (
        ("Left", left_mask, 30, 15),
        ("Right", right_mask, 180, 75),
    ):
        regions.append({
            "name": name, "region_type": "image_mask", "scope": "combined_region",
            "guide_type": "linear", "orientation": "parallel",
            "start": [.1, .5], "end": [.9, .5],
            "gradient_start": start, "gradient_end": start, "curve": 1,
            "fixed_angle": angle, "angle_offset": 0, "reverse": False,
            "mask": _compact_mask(mask), "mask_mode": "grayscale",
            "mask_threshold": .1,
        })
    settings = {
        **krasnow_grating.DEFAULTS,
        "fauxlogram_flow": {"enabled": True, "regions": regions, "strokes": []},
    }
    settings["_compiled_fauxlogram_flow"] = krasnow_grating._prepare_fauxlogram_flow(settings)
    left = krasnow_grating._painted_flow_controls(25, 50, (0, 0, 100, 100), settings)
    right = krasnow_grating._painted_flow_controls(75, 50, (0, 0, 100, 100), settings)
    middle = krasnow_grating._painted_flow_controls(50, 50, (0, 0, 100, 100), settings)
    assert left == pytest.approx((30, 15))
    assert right == pytest.approx((180, 75))
    assert middle is None


def test_image_mask_uncovered_cells_use_another_region_then_main_gradient():
    mask = np.zeros((32, 32), dtype=np.uint8)
    mask[:, 12:20] = 255
    settings = {
        **krasnow_grating.DEFAULTS,
        "fauxlogram_flow": {
            "enabled": True,
            "regions": [
                {
                    "name": "Painted", "region_type": "painted",
                    "scope": "combined_region", "guide_type": "linear",
                    "orientation": "parallel", "start": [.1, .5], "end": [.9, .5],
                    "gradient_start": 30, "gradient_end": 30, "curve": 1,
                    "fixed_angle": 0, "angle_offset": 0, "reverse": False,
                },
                {
                    "name": "Image mask", "region_type": "image_mask",
                    "scope": "combined_region", "guide_type": "linear",
                    "orientation": "parallel", "start": [.1, .5], "end": [.9, .5],
                    "gradient_start": 180, "gradient_end": 180, "curve": 1,
                    "fixed_angle": 45, "angle_offset": 0, "reverse": False,
                    "mask": _compact_mask(mask), "mask_mode": "grayscale",
                    "mask_threshold": 0,
                },
            ],
            "strokes": [{"region": 0, "points": [[.5, .5]], "width": .6}],
        },
    }
    settings["_compiled_fauxlogram_flow"] = krasnow_grating._prepare_fauxlogram_flow(settings)

    assert krasnow_grating._painted_flow_controls(50, 50, (0, 0, 100, 100), settings) == pytest.approx((180, 45))
    assert krasnow_grating._painted_flow_controls(25, 50, (0, 0, 100, 100), settings)[0] == pytest.approx(30)
    assert krasnow_grating._painted_flow_controls(90, 50, (0, 0, 100, 100), settings) is None


def test_flow_painter_exposes_image_masks_as_separate_regions():
    page = (ROOT / "serverless_web" / "index.html").read_text(encoding="utf-8")
    assert "Add image-mask region" in page
    assert "newFlowRegion(flowActiveRegion,'image_mask')" in page
    assert "region.region_type==='image_mask'" in page
    assert "Flat-area fallback angle" in page
    assert "if they overlap, the later region takes precedence" in page
    assert "region.mask&&region.region_type!=='image_mask'" in page


def test_flow_painter_region_errors_identify_position_and_recovery():
    flow = {"regions": [{}, None], "strokes": []}
    message = r"region 2 could not be read.*Reopen the painter.*Reset geometry settings"
    with pytest.raises(ValueError, match=message):
        parse_geometry_style_parameters({"fauxlogram_flow": flow})

    handler = ROOT / "serverless_api" / "handler.py"
    tree = ast.parse(handler.read_text(encoding="utf-8"))
    submit = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "submit_job")
    validate = next(node for node in submit.body if isinstance(node, ast.FunctionDef) and node.name == "validate_fauxlogram_flow")
    validate_mask = next(node for node in submit.body if isinstance(node, ast.FunctionDef) and node.name == "validate_compact_mask")
    namespace = {"base64": base64, "math": math}
    exec(compile(ast.Module(body=[validate_mask, validate], type_ignores=[]), str(handler), "exec"), namespace)
    with pytest.raises(ValueError, match=message):
        namespace["validate_fauxlogram_flow"](flow)

    unsupported_type = {"regions": [{}, {"region_type": "unknown"}], "strokes": []}
    type_message = r"region 2 has an unsupported region type.*Reopen the painter.*Reset geometry settings"
    with pytest.raises(ValueError, match=type_message):
        parse_geometry_style_parameters({"fauxlogram_flow": unsupported_type})
    with pytest.raises(ValueError, match=type_message):
        namespace["validate_fauxlogram_flow"](unsupported_type)

    bad_scope = {"regions": [{}, {"scope": "unknown"}], "strokes": []}
    scope_message = (
        r"region 2 has an invalid Gradient scope.*choose a valid Gradient scope"
        r".*Reset geometry settings"
    )
    with pytest.raises(ValueError, match=scope_message):
        parse_geometry_style_parameters({"fauxlogram_flow": bad_scope})
    with pytest.raises(ValueError, match=scope_message):
        namespace["validate_fauxlogram_flow"](bad_scope)

    bad_guide = {"regions": [{}, {"guide_type": "unknown"}], "strokes": []}
    guide_message = (
        r"region 2 has an invalid Guide type.*choose Linear or Radial"
        r".*Reset geometry settings"
    )
    with pytest.raises(ValueError, match=guide_message):
        parse_geometry_style_parameters({"fauxlogram_flow": bad_guide})
    with pytest.raises(ValueError, match=guide_message):
        namespace["validate_fauxlogram_flow"](bad_guide)

    bad_orientation = {"regions": [{}, {"orientation": "unknown"}], "strokes": []}
    orientation_message = (
        r"region 2 has an invalid Grating orientation.*choose a Grating orientation"
        r".*Reset geometry settings"
    )
    with pytest.raises(ValueError, match=orientation_message):
        parse_geometry_style_parameters({"fauxlogram_flow": bad_orientation})
    with pytest.raises(ValueError, match=orientation_message):
        namespace["validate_fauxlogram_flow"](bad_orientation)

    bad_point = {"regions": [{}, {"start": ["invalid", 0.5]}], "strokes": []}
    point_message = r"region 2 has an invalid guide position.*redraw that region's guide.*Reset geometry settings"
    with pytest.raises(ValueError, match=point_message):
        parse_geometry_style_parameters({"fauxlogram_flow": bad_point})
    with pytest.raises(ValueError, match=point_message):
        namespace["validate_fauxlogram_flow"](bad_point)

    valid_mask = {"width": 8, "height": 8, "data": base64.b64encode(bytes(64)).decode("ascii")}
    bad_mask_mode = {"regions": [{}, {"mask": valid_mask, "mask_mode": "unknown"}], "strokes": []}
    mode_message = r"region 2 has an invalid mask Interpretation.*choose Grayscale gradient map or Silhouette"
    with pytest.raises(ValueError, match=mode_message):
        parse_geometry_style_parameters({"fauxlogram_flow": bad_mask_mode})
    with pytest.raises(ValueError, match=mode_message):
        namespace["validate_fauxlogram_flow"](bad_mask_mode)

    bad_inversion = {"regions": [{}, {"mask": valid_mask, "mask_invert": []}], "strokes": []}
    with pytest.raises(ValueError, match=r"region 2 has an invalid Invert mask setting"):
        namespace["validate_fauxlogram_flow"](bad_inversion)

    bad_mask = {"regions": [{}, {"mask": {}}], "strokes": []}
    with pytest.raises(ValueError, match=r"region 2's image mask couldn't be used"):
        parse_geometry_style_parameters({"fauxlogram_flow": bad_mask})
    with pytest.raises(ValueError, match=r"region 2's image mask couldn't be used"):
        namespace["validate_fauxlogram_flow"](bad_mask)

    missing_region = {"regions": [{}], "strokes": [{"region": 7, "points": [[0.5, 0.5]]}]}
    stroke_message = r"brush stroke 1 refers to a region that is no longer available.*Reset geometry settings"
    with pytest.raises(ValueError, match=stroke_message):
        parse_geometry_style_parameters({"fauxlogram_flow": missing_region})
    with pytest.raises(ValueError, match=stroke_message):
        namespace["validate_fauxlogram_flow"](missing_region)


def test_invalid_swatch_geometry_identifies_the_swatch_and_valid_choices():
    with pytest.raises(ValueError, match=r"routing for #FF0000 has an unsupported geometry.*Vectors, Glyphs, or Krasnow"):
        parse_geometry_style_parameters({
            "assignments": {"#FF0000": "unknown"},
            "glyphs": {},
            "krasnow_grating": {},
        })


def test_geometry_parameter_parser_preserves_flow_region_mask():
    values = np.zeros((16, 16), dtype=np.uint8)
    values[:, :8] = 255
    mask = _compact_mask(values)
    parsed = parse_geometry_style_parameters({
        "fauxlogram_flow": {
            "enabled": True,
            "regions": [{
                "name": "Masked", "scope": "combined_region",
                "region_type": "image_mask",
                "guide_type": "radial", "orientation": "parallel",
                "start": [.5, .5], "end": [.9, .5],
                "mask": mask, "mask_name": "star.png",
                "mask_mode": "grayscale", "mask_threshold": .25,
                "mask_invert": True, "mask_offset": [.2, -.1],
            }],
            "strokes": [],
        },
    })

    region = parsed["fauxlogram_flow"]["regions"][0]
    assert region["mask"] == mask
    assert region["region_type"] == "image_mask"
    assert region["mask_mode"] == "grayscale"
    assert region["mask_invert"] is True
    assert region["mask_offset"] == [.2, -.1]


def test_fauxlogram_flow_mask_offset_repositions_the_active_area():
    values = np.zeros((16, 16), dtype=np.uint8)
    values[:, :8] = 255
    settings = {
        **krasnow_grating.DEFAULTS,
        "fauxlogram_flow": {
            "enabled": True,
            "regions": [{
                "name": "Moved", "scope": "combined_region",
                "guide_type": "linear", "orientation": "parallel",
                "start": [.1, .5], "end": [.9, .5],
                "gradient_start": 20, "gradient_end": 220, "curve": 1,
                "fixed_angle": 0, "angle_offset": 0, "reverse": False,
                "mask": _compact_mask(values), "mask_mode": "silhouette",
                "mask_threshold": .5, "mask_offset": [.5, 0],
            }],
            "strokes": [],
        },
    }
    settings["_compiled_fauxlogram_flow"] = krasnow_grating._prepare_fauxlogram_flow(settings)

    assert krasnow_grating._painted_flow_controls(20, 50, (0, 0, 100, 100), settings) is None
    assert krasnow_grating._painted_flow_controls(70, 50, (0, 0, 100, 100), settings) is not None


def test_staging_ui_exposes_custom_glyph_and_flow_mask_uploads():
    page = (ROOT / "serverless_web" / "index.html").read_text(encoding="utf-8")
    assert "['custom','Custom Uploaded Glyph']" in page
    assert "data-custom-glyph-file" in page
    assert "repeating-conic-gradient(#fff 0 25%,#000 0 50%)" in page
    assert 'id="flowMaskFile"' in page
    assert "flowHasContent()" in page
    assert "normalizeShapeImage" in page
    assert 'data-flow-tool="move"' in page
    assert "mask_offset" in page

import os
import sys
from pathlib import Path

from PIL import Image
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
        "patch_size_mm": .4, "line_spacing_mm": .06,
        "hue_line_spacing_minimum_mm": .05,
        "hue_line_spacing_maximum_mm": .07,
        "speed_spread": 1,
    }) == {
        "cell_shape": "hexagon", "preserve_black": 0,
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
    assert "['invert_fill',false]" in page
    assert "syncGeometryToggleCompatibility" in page
    assert "Every output layer is made mutually exclusive before export." in page
    assert "const KRASNOW_GEOMETRY=PRESETS.abstract_krasnow_grating" in page
    assert 'id="geometryRoutingGrid"' in page
    assert 'data-route-bulk="glyphs"' in page
    assert 'data-route-bulk="krasnow_grating"' in page
    assert "posterize_colors" not in page
    assert "This requires a Holographic Cut Setting" in page
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

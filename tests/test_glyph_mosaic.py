import os

from PIL import Image
from shapely.geometry import box

from lib.abstract_filters import FULL_PALETTE_FILTERS, MODULES, glyph_mosaic

os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-2")

from services import parse_abstract_filter_parameters


TARGET_COLORS = {
    "#FF0000": ["Red", 2, "Red"],
    "#0000FF": ["Blue", 3, "Blue"],
    "#000000": ["Black", 0, "Black"],
}


def settings(**overrides):
    values = {
        **glyph_mosaic.DEFAULTS,
        "_canvas_bounds": (0, 0, 8, 4),
        "_scale_factor": 1,
        "_angle_image": Image.new("L", (8, 4), 96),
    }
    values.update(overrides)
    return values


def test_filter_is_registered_for_full_palette_processing():
    assert MODULES["glyph_mosaic"] is glyph_mosaic
    assert "glyph_mosaic" in FULL_PALETTE_FILTERS
    assert glyph_mosaic.DEFAULTS["glyph_shape"] == "diamond"


def test_all_exposed_shapes_emit_geometry():
    layers = {"#FF0000": box(0, 0, 8, 4)}
    target = {"#FF0000": TARGET_COLORS["#FF0000"]}
    for shape in glyph_mosaic.GLYPH_SHAPES:
        result = glyph_mosaic.remap_layers(
            layers, target, settings(glyph_shape=shape, grid_angle=0)
        )
        assert result["#FF0000"].area > 0, shape


def test_layers_are_exclusive_and_mixed_shapes_are_deterministic():
    layers = {
        "#FF0000": box(0, 0, 4, 4),
        "#0000FF": box(4, 0, 8, 4),
    }
    first = glyph_mosaic.remap_layers(
        layers, TARGET_COLORS, settings(glyph_shape="mixed", seed=19)
    )
    second = glyph_mosaic.remap_layers(
        layers, TARGET_COLORS, settings(glyph_shape="mixed", seed=19)
    )
    assert first["#FF0000"].intersection(first["#0000FF"]).area <= 1e-12
    assert first["#FF0000"].wkb == second["#FF0000"].wkb
    assert first["#0000FF"].wkb == second["#0000FF"].wkb


def test_mixed_shape_seed_selects_another_repeatable_arrangement():
    layers = {"#FF0000": box(0, 0, 8, 4)}
    target = {"#FF0000": TARGET_COLORS["#FF0000"]}
    first = glyph_mosaic.remap_layers(
        layers, target, settings(glyph_shape="mixed", seed=1, grid_angle=0)
    )["#FF0000"]
    second = glyph_mosaic.remap_layers(
        layers, target, settings(glyph_shape="mixed", seed=2, grid_angle=0)
    )["#FF0000"]
    assert first.wkb != second.wkb


def test_shape_and_checkbox_parameters_are_accepted():
    assert parse_abstract_filter_parameters(
        '{"glyph_shape":"star","black_only":false,"invert":true}'
    ) == {"glyph_shape": "star", "black_only": 0, "invert": 1}


def test_unknown_shape_is_rejected():
    try:
        glyph_mosaic.remap_layers(
            {"#FF0000": box(0, 0, 2, 2)},
            {"#FF0000": TARGET_COLORS["#FF0000"]},
            settings(glyph_shape="unknown"),
        )
    except ValueError as error:
        assert "not supported" in str(error)
    else:
        raise AssertionError("Expected an unknown glyph to be rejected")


def test_staging_ui_and_api_expose_glyph_mosaic():
    page = open("serverless_web/index.html", encoding="utf-8").read()
    api = open("serverless_api/handler.py", encoding="utf-8").read()
    assert 'value="abstract_glyph_mosaic"' in page
    assert "'mixed','Mixed Shapes'" in page
    declaration = api.split("ABSTRACT_FILTERS = {", 1)[1].split("}", 1)[0]
    assert '"glyph_mosaic"' in declaration

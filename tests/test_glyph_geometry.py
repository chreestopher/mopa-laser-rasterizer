import base64
import sys
from pathlib import Path

from PIL import Image
from shapely.geometry import box


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import geometry_styles
import glyph_geometry
from abstract_filters import FULL_PALETTE_FILTERS, MODULES


TARGET_COLORS = {
    "#FF0000": ["Red", 2, "Red"],
    "#0000FF": ["Blue", 3, "Blue"],
    "#000000": ["Black", 0, "Black"],
}


def settings(**overrides):
    values = {
        **glyph_geometry.DEFAULTS,
        "_canvas_bounds": (0, 0, 8, 4),
        "_scale_factor": 1,
        "_angle_image": Image.new("L", (8, 4), 96),
    }
    values.update(overrides)
    return values


def test_abstract_filter_is_retired_but_geometry_style_remains_registered():
    assert "glyph_mosaic" not in MODULES
    assert "glyph_mosaic" not in FULL_PALETTE_FILTERS
    assert geometry_styles.module_for_style("glyphs") is glyph_geometry
    assert glyph_geometry.DEFAULTS["glyph_shape"] == "diamond"


def test_all_exposed_shapes_emit_geometry():
    layers = {"#FF0000": box(0, 0, 8, 4)}
    target = {"#FF0000": TARGET_COLORS["#FF0000"]}
    for shape in glyph_geometry.GLYPH_SHAPES:
        overrides = {"glyph_shape": shape, "grid_angle": 0}
        if shape == "custom":
            overrides["custom_glyph_mask"] = {
                "width": 16,
                "height": 16,
                "data": base64.b64encode(bytes([255]) * 16 * 16).decode("ascii"),
            }
        result = glyph_geometry.remap_layers(
            layers, target, settings(**overrides)
        )
        assert result["#FF0000"].area > 0, shape


def test_layers_are_exclusive_and_mixed_shapes_are_deterministic():
    layers = {
        "#FF0000": box(0, 0, 4, 4),
        "#0000FF": box(4, 0, 8, 4),
    }
    first = glyph_geometry.remap_layers(
        layers, TARGET_COLORS, settings(glyph_shape="mixed", seed=19)
    )
    second = glyph_geometry.remap_layers(
        layers, TARGET_COLORS, settings(glyph_shape="mixed", seed=19)
    )
    assert first["#FF0000"].intersection(first["#0000FF"]).area <= 1e-12
    assert first["#FF0000"].wkb == second["#FF0000"].wkb
    assert first["#0000FF"].wkb == second["#0000FF"].wkb


def test_unknown_shape_is_rejected():
    try:
        glyph_geometry.remap_layers(
            {"#FF0000": box(0, 0, 2, 2)},
            {"#FF0000": TARGET_COLORS["#FF0000"]},
            settings(glyph_shape="unknown"),
        )
    except ValueError as error:
        assert "not supported" in str(error)
    else:
        raise AssertionError("Expected an unknown glyph to be rejected")


def test_ui_api_and_docs_do_not_expose_retired_abstract_filter():
    page = (ROOT / "serverless_web" / "index.html").read_text(encoding="utf-8")
    template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    api = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")
    docs = (ROOT / "routes" / "docs.py").read_text(encoding="utf-8")
    service = (ROOT / "services.py").read_text(encoding="utf-8")

    for source in (page, template, api, docs, service):
        assert "glyph_mosaic" not in source
        assert "Glyph Mosaic" not in source
    assert "Glyphs" in page
    assert 'value="glyphs"' in page

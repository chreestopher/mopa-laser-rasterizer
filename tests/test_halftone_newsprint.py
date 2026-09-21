import math

from PIL import Image
from shapely.geometry import box

from lib.abstract_filters import FULL_PALETTE_FILTERS, MODULES, manifest
from lib.abstract_filters import halftone_newsprint


TARGET_COLORS = {
    "#FF0000": ["Red", 2, "Red"],
    "#0000FF": ["Blue", 3, "Blue"],
    "#000000": ["Black", 0, "Black"],
}


def settings(**overrides):
    values = {
        **halftone_newsprint.DEFAULTS,
        "_canvas_bounds": (0, 0, 8, 4),
        "_scale_factor": 1,
        "_angle_image": Image.new("L", (8, 4), 96),
    }
    values.update(overrides)
    return values


def test_filter_is_registered_as_full_palette_filter():
    assert MODULES["halftone_newsprint"] is halftone_newsprint
    assert "halftone_newsprint" in FULL_PALETTE_FILTERS
    defaults = manifest()["halftone_newsprint"]["defaults"]
    assert defaults["cell_size_mm"] == 0.6
    assert defaults["minimum_dot_ratio"] == 0.48
    assert defaults["maximum_dot_ratio"] == 0.97
    assert defaults["non_black_dot_density"] == 2.3
    assert defaults["tone_curve"] == 0.75
    assert defaults["contrast"] == 2.0
    assert defaults["grid_angle"] == -45.0


def test_numeric_control_ranges_are_centered_on_engraving_validated_defaults():
    filter_manifest = manifest()["halftone_newsprint"]
    defaults = filter_manifest["defaults"]
    for control in filter_manifest["controls"]:
        if control["name"] in {"square_dots", "invert", "black_only"}:
            continue
        midpoint = (control["min"] + control["max"]) / 2
        assert math.isclose(defaults[control["name"]], midpoint, abs_tol=1e-12)


def test_default_bright_mark_uses_validated_minimum_diameter():
    ratio = halftone_newsprint._dot_ratio(255, halftone_newsprint.DEFAULTS)
    assert math.isclose(ratio, 0.48, rel_tol=1e-9)


def test_default_increases_non_black_area_without_changing_black():
    base_ratio = 0.5
    color_ratio = halftone_newsprint._adjust_dot_ratio_for_color(
        base_ratio, "#FF0000", False, halftone_newsprint.DEFAULTS
    )
    black_ratio = halftone_newsprint._adjust_dot_ratio_for_color(
        base_ratio, "#000000", False, halftone_newsprint.DEFAULTS
    )

    assert math.isclose(color_ratio * color_ratio, 2.3 * base_ratio * base_ratio)
    assert black_ratio == base_ratio


def test_non_black_density_is_tunable_clamped_and_disabled_in_black_only_mode():
    assert halftone_newsprint._adjust_dot_ratio_for_color(
        0.5, "#00FF00", False, {"non_black_dot_density": 1}
    ) == 0.5


def test_glyph_density_mode_preserves_configured_size_endpoints():
    configured = {
        "minimum_dot_ratio": .2,
        "maximum_dot_ratio": .8,
        "non_black_dot_density": 2.3,
        "_preserve_dot_ratio_range": 1,
    }
    midpoint = math.sqrt((.2 ** 2 + .8 ** 2) / 2)

    assert halftone_newsprint._adjust_dot_ratio_for_color(
        .2, "#FF0000", False, configured
    ) == .2
    assert math.isclose(
        halftone_newsprint._adjust_dot_ratio_for_color(
            .8, "#FF0000", False, configured
        ),
        .8,
    )
    adjusted_midpoint = halftone_newsprint._adjust_dot_ratio_for_color(
        midpoint, "#FF0000", False, configured
    )
    assert midpoint < adjusted_midpoint < .8


def test_density_doubles_emitted_color_area_and_leaves_emitted_black_unchanged():
    layers = {
        "#000000": box(0, 0, 2, 2),
        "#FF0000": box(2, 0, 4, 2),
    }
    common = settings(
        _canvas_bounds=(0, 0, 4, 2),
        _angle_image=Image.new("L", (4, 2), 127),
        cell_size_mm=2,
        minimum_dot_ratio=0.4,
        maximum_dot_ratio=0.4,
        square_dots=1,
        grid_angle=0,
    )
    baseline = halftone_newsprint.remap_layers(
        layers, TARGET_COLORS, {**common, "non_black_dot_density": 1}
    )
    doubled = halftone_newsprint.remap_layers(
        layers, TARGET_COLORS, {**common, "non_black_dot_density": 2}
    )

    assert math.isclose(doubled["#FF0000"].area, 2 * baseline["#FF0000"].area)
    assert math.isclose(doubled["#000000"].area, baseline["#000000"].area)
    assert halftone_newsprint._adjust_dot_ratio_for_color(
        0.8, "#00FF00", False, {"non_black_dot_density": 4}
    ) == 1.0
    assert halftone_newsprint._adjust_dot_ratio_for_color(
        0.5, "#00FF00", True, {"non_black_dot_density": 4}
    ) == 0.5


def test_matrix_is_deterministic_and_layers_do_not_overlap():
    layers = {
        "#FF0000": box(0, 0, 4, 4),
        "#0000FF": box(4, 0, 8, 4),
    }
    first = halftone_newsprint.remap_layers(layers, TARGET_COLORS, settings())
    second = halftone_newsprint.remap_layers(layers, TARGET_COLORS, settings())

    assert set(first) == {"#FF0000", "#0000FF"}
    assert first["#FF0000"].wkb == second["#FF0000"].wkb
    assert first["#0000FF"].wkb == second["#0000FF"].wkb
    assert first["#FF0000"].intersection(first["#0000FF"]).area <= 1e-12


def test_black_only_places_every_mark_on_official_black_layer():
    layers = {
        "#FF0000": box(0, 0, 4, 4),
        "#0000FF": box(4, 0, 8, 4),
    }
    result = halftone_newsprint.remap_layers(
        layers, TARGET_COLORS, settings(black_only=1)
    )

    assert set(result) == {"#000000"}
    assert result["#000000"].area > 0


def test_black_only_requires_assigned_official_black_setting():
    try:
        halftone_newsprint.remap_layers(
            {"#FF0000": box(0, 0, 4, 4)},
            {"#FF0000": TARGET_COLORS["#FF0000"]},
            settings(black_only=1),
        )
    except ValueError as error:
        assert "requires the official Black swatch" in str(error)
    else:
        raise AssertionError("Expected Black Only mode without Black to be rejected")


def test_darker_source_cells_create_larger_marks():
    tone = Image.new("L", (4, 2), 255)
    for y in range(2):
        for x in range(2):
            tone.putpixel((x, y), 0)
    result = halftone_newsprint.remap_layers(
        {"#FF0000": box(0, 0, 4, 2)},
        {"#FF0000": TARGET_COLORS["#FF0000"]},
        settings(
            _canvas_bounds=(0, 0, 4, 2),
            _angle_image=tone,
            cell_size_mm=2,
        ),
    )["#FF0000"]

    dark_area = result.intersection(box(0, 0, 2, 2)).area
    light_area = result.intersection(box(2, 0, 4, 2)).area
    assert dark_area > light_area


def test_square_control_changes_mark_shape_without_changing_cell_ownership():
    layers = {"#FF0000": box(0, 0, 2, 2)}
    target = {"#FF0000": TARGET_COLORS["#FF0000"]}
    common = settings(
        _canvas_bounds=(0, 0, 2, 2),
        _angle_image=Image.new("L", (2, 2), 0),
        cell_size_mm=2,
        maximum_dot_ratio=0.8,
        non_black_dot_density=1,
        tone_curve=1,
        contrast=1,
        grid_angle=0,
    )
    circle = halftone_newsprint.remap_layers(layers, target, common)["#FF0000"]
    square = halftone_newsprint.remap_layers(
        layers, target, {**common, "square_dots": 1}
    )["#FF0000"]

    assert square.area > circle.area
    assert math.isclose(square.area, 2.56, rel_tol=1e-6)


def test_rotated_matrix_stays_inside_canvas():
    canvas = box(0, 0, 8, 4)
    result = halftone_newsprint.remap_layers(
        {"#FF0000": canvas},
        {"#FF0000": TARGET_COLORS["#FF0000"]},
        settings(grid_angle=30, square_dots=1),
    )["#FF0000"]
    assert result.difference(canvas).area == 0


def test_progress_is_batched_and_reports_completion():
    messages = []
    halftone_newsprint.remap_layers(
        {"#FF0000": box(0, 0, 8, 4)},
        {"#FF0000": TARGET_COLORS["#FF0000"]},
        settings(_progress_logger=messages.append),
    )
    assert messages[0].startswith("Halftone Newsprint: starting")
    assert messages[-1].startswith("Halftone Newsprint: matrix complete")
    assert len(messages) <= halftone_newsprint.PROGRESS_BATCHES + 2


def test_progress_row_ranges_are_contiguous_without_overlap():
    messages = []
    halftone_newsprint.remap_layers(
        {"#FF0000": box(0, 0, 84, 84)},
        {"#FF0000": TARGET_COLORS["#FF0000"]},
        settings(
            _canvas_bounds=(0, 0, 84, 84),
            _scale_factor=0.6,
            _angle_image=Image.new("L", (84, 84), 96),
            _progress_logger=messages.append,
            grid_angle=0,
        ),
    )
    covered_rows = []
    for message in messages:
        if "completed rows" not in message:
            continue
        row_range = message.split("completed rows ", 1)[1].split(" of ", 1)[0]
        start, end = map(int, row_range.split("-"))
        covered_rows.extend(range(start, end + 1))
    assert covered_rows == list(range(1, 85))


def test_excessive_matrix_has_actionable_error():
    try:
        halftone_newsprint.remap_layers(
            {"#FF0000": box(0, 0, 1000, 1000)},
            {"#FF0000": TARGET_COLORS["#FF0000"]},
            settings(
                _canvas_bounds=(0, 0, 1000, 1000),
                _scale_factor=1,
                cell_size_mm=0.2,
            ),
        )
    except ValueError as error:
        assert "Increase Cell Size MM" in str(error)
    else:
        raise AssertionError("Expected an oversized halftone matrix to be rejected")


def test_staging_ui_exposes_filter_and_all_controls():
    source = open("serverless_web/index.html", encoding="utf-8").read()
    assert 'value="abstract_halftone_newsprint"' in source
    assert "input.type==='checkbox'?Number(input.checked):input.tagName==='SELECT'?input.value:Number(input.value)" in source
    for control_name in halftone_newsprint.DEFAULTS:
        assert control_name in source


def test_worker_normalizes_halftone_checkboxes_to_numeric_flags():
    source = open("services.py", encoding="utf-8").read()
    assert '"square_dots", "invert"' in source
    assert "clean[key] = int(value)" in source


def test_serverless_api_accepts_filter_name():
    source = open("serverless_api/handler.py", encoding="utf-8").read()
    declaration = source.split("ABSTRACT_FILTERS = {", 1)[1].split("}", 1)[0]
    assert '"halftone_newsprint"' in declaration

from pathlib import Path

import pytest
from PIL import Image
from shapely.geometry import box

from lib.abstract_filters import FULL_PALETTE_FILTERS, MODULES, manifest
from lib.abstract_filters import optical_color_mix
from services import parse_abstract_filter_parameters


ROOT = Path(__file__).resolve().parents[1]
TARGET_COLORS = {
    "#FF0000": (0, 2, "Red"),
    "#0000FF": (0, 1, "Blue"),
}


def settings(**overrides):
    values = {
        **optical_color_mix.DEFAULTS,
        "_canvas_bounds": (0, 0, 8, 8),
        "_scale_factor": 1,
        "_source_color_image": Image.new("RGB", (8, 8), (128, 0, 128)),
        "dot_pitch_mm": 1,
        "mix_cell_dots": 2,
        "dot_size_ratio": 0.6,
        "direct_color_preference": 0,
    }
    values.update(overrides)
    return values


def test_filter_is_registered_for_full_palette_and_source_color():
    assert MODULES["optical_color_mix"] is optical_color_mix
    assert "optical_color_mix" in FULL_PALETTE_FILTERS
    assert optical_color_mix.USES_SOURCE_COLOR is True
    assert optical_color_mix.PRESERVE_SOURCE_BLACK is True
    assert manifest()["optical_color_mix"]["defaults"]["mixing_model"] == "lab"


@pytest.mark.parametrize("model", ["lab", "rgb", "hsv"])
def test_purple_source_uses_nonoverlapping_red_blue_mixture(model):
    result = optical_color_mix.remap_layers(
        {"#FF0000": box(0, 0, 8, 8)},
        TARGET_COLORS,
        settings(mixing_model=model),
    )

    assert set(result) == {"#FF0000", "#0000FF"}
    assert result["#FF0000"].area > 0
    assert result["#0000FF"].area > 0
    assert result["#FF0000"].intersection(result["#0000FF"]).area == 0


def test_output_is_deterministic_for_same_seed():
    arguments = (
        {"#FF0000": box(0, 0, 8, 8)},
        TARGET_COLORS,
        settings(pattern_seed=37),
    )
    first = optical_color_mix.remap_layers(*arguments)
    second = optical_color_mix.remap_layers(*arguments)

    assert list(first) == list(second)
    assert {key: value.wkb for key, value in first.items()} == {
        key: value.wkb for key, value in second.items()
    }


def test_disabling_vector_retention_renders_direct_match_as_dots():
    source_geometry = box(0, 0, 8, 8)
    result = optical_color_mix.remap_layers(
        {"#FF0000": source_geometry},
        TARGET_COLORS,
        settings(
            _source_color_image=Image.new("RGB", (8, 8), (255, 0, 0)),
            keep_available_colors_as_vectors=0,
        ),
    )

    assert set(result) == {"#FF0000"}
    assert 0 < result["#FF0000"].area < source_geometry.area


def test_direct_color_preference_can_avoid_an_unnecessary_mixture():
    source_geometry = box(0, 0, 8, 8)
    result = optical_color_mix.remap_layers(
        {"#FF0000": source_geometry},
        TARGET_COLORS,
        settings(direct_color_preference=1),
    )

    assert len(result) == 1
    assert result["#FF0000"].equals(source_geometry)


@pytest.mark.parametrize(
    ("square_dots", "pattern_seed"),
    [(0, 1), (1, 29)],
)
def test_direct_palette_areas_stay_vectors_while_unavailable_colors_mix(
    square_dots, pattern_seed
):
    source = Image.new("RGB", (8, 8), (128, 0, 128))
    for y in range(8):
        for x in range(4):
            source.putpixel((x, y), (255, 0, 0))
    result = optical_color_mix.remap_layers(
        {"#FF0000": box(0, 0, 8, 8)},
        TARGET_COLORS,
        settings(
            _source_color_image=source,
            square_dots=square_dots,
            pattern_seed=pattern_seed,
        ),
    )

    direct_half = box(0, 0, 4, 8)
    mixed_half = box(4, 0, 8, 8)
    assert result["#FF0000"].intersection(direct_half).equals(direct_half)
    assert result["#0000FF"].intersection(direct_half).is_empty
    assert result["#FF0000"].intersection(mixed_half).area > 0
    assert result["#0000FF"].intersection(mixed_half).area > 0
    assert result["#FF0000"].intersection(result["#0000FF"]).area == 0


def test_matrix_limit_has_actionable_error():
    with pytest.raises(ValueError, match="Increase Dot Pitch MM"):
        optical_color_mix.remap_layers(
            {"#FF0000": box(0, 0, 1000, 1000)},
            TARGET_COLORS,
            settings(
                _canvas_bounds=(0, 0, 1000, 1000),
                _source_color_image=Image.new("RGB", (8, 8), (128, 0, 128)),
                dot_pitch_mm=0.15,
            ),
        )


def test_progress_is_batched_and_names_matching_model():
    messages = []
    optical_color_mix.remap_layers(
        {"#FF0000": box(0, 0, 8, 8)},
        TARGET_COLORS,
        settings(_progress_logger=messages.append, mixing_model="rgb"),
    )

    assert "RGB matching" in messages[0]
    assert messages[-1].startswith("Optical Color Mix: hybrid mapping complete")
    assert "direct-vector cells" in messages[-1]
    assert "mixed cells" in messages[-1]
    assert len(messages) <= optical_color_mix.PROGRESS_BATCHES + 2


def test_worker_boundary_accepts_only_supported_mixing_models():
    assert parse_abstract_filter_parameters('{"mixing_model":"lab"}') == {
        "mixing_model": "lab"
    }
    with pytest.raises(ValueError, match="must be numeric"):
        parse_abstract_filter_parameters('{"mixing_model":"xyz"}')


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [("true", 1), ("false", 0)],
)
def test_worker_boundary_normalizes_vector_retention_checkbox(raw_value, expected):
    parsed = parse_abstract_filter_parameters(
        '{"keep_available_colors_as_vectors":' + raw_value + '}'
    )
    assert parsed["keep_available_colors_as_vectors"] == expected


def test_staging_and_template_ui_expose_filter_controls():
    staging = (ROOT / "serverless_web" / "index.html").read_text(encoding="utf-8")
    template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    api = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")

    for source in (staging, template):
        assert "abstract_optical_color_mix" in source
        for control_name in optical_color_mix.DEFAULTS:
            assert control_name in source
    assert 'input.tagName===\'SELECT\'?input.value' in staging
    declaration = api.split("ABSTRACT_FILTERS = {", 1)[1].split("}", 1)[0]
    assert '"optical_color_mix"' in declaration

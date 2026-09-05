import sys
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
LIB_DIR = ROOT / "lib"
sys.path.insert(0, str(LIB_DIR))

for module_name in list(sys.modules):
    if module_name == "vector_processing" or module_name == "abstract_filters" \
            or module_name.startswith("abstract_filters."):
        del sys.modules[module_name]

import vector_processing


TARGET_COLORS = {
    "#B4B4B4": (0, 8, "Light-Gray"),
    "#000000": (0, 0, "Black"),
    "#4A6FE3": (225, 19, "Periwinkle-Blue"),
    "#8CD78C": (120, 21, "Sage-Green"),
    "#00E0E0": (180, 6, "Cyan"),
    "#004754": (189, 27, "Teal"),
    "#808080": (2, 16, "Medium-Gray"),
}

BLUE_SHADE_COLORS = {
    "#000000": (0, 0, "Black"),
    "#0000FF": (240, 1, "Blue"),
    "#4A6FE3": (225, 19, "Periwinkle-Blue"),
    "#00E0E0": (180, 6, "Cyan"),
    "#004754": (189, 27, "Teal"),
    "#B4B4B4": (0, 8, "Light-Gray"),
}


def test_saturated_light_blue_cannot_collapse_to_light_gray(tmp_path):
    source_path = tmp_path / "light-blue.png"
    Image.new("RGB", (1, 1), (108, 202, 236)).save(source_path)

    quantized = vector_processing.prepare_raster_image(
        raster_image_path=source_path,
        new_height=0,
        new_width=1,
        quantize_colors=len(TARGET_COLORS),
        target_colors=TARGET_COLORS,
    )

    assert quantized.getpixel((0, 0)) == (74, 111, 227)


def test_low_saturation_source_can_still_use_light_gray(tmp_path):
    source_path = tmp_path / "neutral.png"
    Image.new("RGB", (1, 1), (184, 188, 190)).save(source_path)

    quantized = vector_processing.prepare_raster_image(
        raster_image_path=source_path,
        new_height=0,
        new_width=1,
        quantize_colors=len(TARGET_COLORS),
        target_colors=TARGET_COLORS,
    )

    assert quantized.getpixel((0, 0)) == (180, 180, 180)


def test_moderately_tinted_neutral_is_not_forced_to_blue():
    source = Image.new("RGB", (1, 1), (135, 190, 255))
    initially_neutral = Image.new("RGB", (1, 1), (180, 180, 180))

    corrected = vector_processing.preserve_saturated_palette_colors(
        source,
        initially_neutral,
        TARGET_COLORS,
    )

    assert corrected.getpixel((0, 0)) == (180, 180, 180)


def test_low_saturation_pixel_misassigned_to_blue_returns_to_neutral():
    source = Image.new("RGB", (1, 1), (184, 188, 190))
    initially_blue = Image.new("RGB", (1, 1), (74, 111, 227))

    corrected = vector_processing.distinguish_blue_palette_shades(
        source,
        initially_blue,
        BLUE_SHADE_COLORS,
    )

    assert corrected.getpixel((0, 0)) == (180, 180, 180)


def test_black_assignment_is_not_treated_as_neutral_collapse(tmp_path):
    source_path = tmp_path / "black.png"
    Image.new("RGB", (1, 1), (2, 4, 8)).save(source_path)

    quantized = vector_processing.prepare_raster_image(
        raster_image_path=source_path,
        new_height=0,
        new_width=1,
        quantize_colors=len(TARGET_COLORS),
        target_colors=TARGET_COLORS,
    )

    assert quantized.getpixel((0, 0)) == (0, 0, 0)


def test_blue_family_uses_tone_to_separate_blue_from_periwinkle(tmp_path):
    source_path = tmp_path / "blue-shades.png"
    source = Image.new("RGB", (2, 1))
    source.putdata([
        (0, 80, 180),
        (65, 170, 235),
    ])
    source.save(source_path)

    quantized = vector_processing.prepare_raster_image(
        raster_image_path=source_path,
        new_height=0,
        new_width=2,
        quantize_colors=len(BLUE_SHADE_COLORS),
        target_colors=BLUE_SHADE_COLORS,
    )

    assert [quantized.getpixel((x, 0)) for x in range(2)] == [
        (0, 0, 255),
        (74, 111, 227),
    ]


def test_blue_tone_split_does_not_reassign_cyan_or_teal(tmp_path):
    source_path = tmp_path / "cyan-teal.png"
    source = Image.new("RGB", (2, 1))
    source.putdata([
        (0, 224, 224),
        (0, 71, 84),
    ])
    source.save(source_path)

    quantized = vector_processing.prepare_raster_image(
        raster_image_path=source_path,
        new_height=0,
        new_width=2,
        quantize_colors=len(BLUE_SHADE_COLORS),
        target_colors=BLUE_SHADE_COLORS,
    )

    assert [quantized.getpixel((x, 0)) for x in range(2)] == [
        (0, 224, 224),
        (0, 71, 84),
    ]


def test_closest_swatch_mode_skips_hue_protection(tmp_path):
    source_path = tmp_path / "closest-light-blue.png"
    Image.new("RGB", (1, 1), (108, 202, 236)).save(source_path)

    quantized = vector_processing.prepare_raster_image(
        raster_image_path=source_path,
        new_height=0,
        new_width=1,
        quantize_colors=len(TARGET_COLORS),
        target_colors=TARGET_COLORS,
        color_matching={"color_matching_mode": "closest"},
    )

    assert quantized.getpixel((0, 0)) == (180, 180, 180)


def test_color_matching_presets_and_custom_weights_are_resolved_safely():
    assert vector_processing.resolve_color_matching({"color_matching_mode": "hue"}) == {
        "mode": "hue", "preserve_chroma": True, "separate_blue_shades": True,
        "hue_weight": 8.0, "saturation_weight": 1.0, "lightness_weight": 1.0,
    }
    assert vector_processing.resolve_color_matching({"color_matching_mode": "shades"})["lightness_weight"] == 4.0
    custom = vector_processing.resolve_color_matching({
        "color_matching_mode": "custom",
        "color_matching_hue_weight": 7.5,
        "color_matching_saturation_weight": 2.5,
        "color_matching_lightness_weight": 12,
    })
    assert custom["mode"] == "custom"
    assert custom["hue_weight"] == 7.5
    assert custom["saturation_weight"] == 2.5
    assert custom["lightness_weight"] == 10.0
    assert vector_processing.resolve_color_matching({
        "color_matching_mode": "custom",
        "color_matching_hue_weight": 0,
        "color_matching_saturation_weight": 0,
        "color_matching_lightness_weight": 0,
    })["mode"] == "balanced"

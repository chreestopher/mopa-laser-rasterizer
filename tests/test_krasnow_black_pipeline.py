import sys
from pathlib import Path

import numpy as np
from PIL import Image
from shapely.geometry import box


ROOT = Path(__file__).resolve().parents[1]
LIB_DIR = ROOT / "lib"
sys.path.insert(0, str(LIB_DIR))

# The experiment suite intentionally imports its cloned modules under these
# same top-level names. Ensure this production regression test cannot silently
# exercise the experimental copies when both suites are collected together.
for module_name in list(sys.modules):
    if module_name == "vector_processing" or module_name == "abstract_filters" \
            or module_name.startswith("abstract_filters."):
        del sys.modules[module_name]

import vector_processing


def test_krasnow_uses_source_faithful_vector_defaults():
    krasnow = vector_processing.ABSTRACT_FILTER_MODULES["krasnow_grating"]
    assert krasnow.VECTOR_DEFAULTS == {
        "min_island_area": 0,
        "simplification_factor": 0.0,
        "smoothing_radius": 0.001,
    }


def test_krasnow_does_not_build_gratings_from_black_geometry():
    krasnow = vector_processing.ABSTRACT_FILTER_MODULES["krasnow_grating"]
    remapped = krasnow.remap_layers(
        processed_layers={"#000000": box(0, 0, 2, 2)},
        target_colors={
            "#000000": (0, 0, "Black"),
            "#0000FF": (240, 1, "Blue"),
            "#FF0000": (0, 2, "Red"),
        },
        settings={
            "_canvas_bounds": (0, 0, 2, 2),
            "_scale_factor": 1,
            "patch_size_mm": 1,
            "line_spacing_mm": 0.25,
            "angle_min": 0,
            "angle_max": 0,
        },
    )

    assert remapped == {}


def test_krasnow_black_mask_replaces_only_the_black_layer():
    blue = box(0, 0, 1, 1).boundary
    old_black = box(10, 10, 11, 11)
    source = Image.new("RGB", (2, 1))
    source.putdata([(0, 0, 0), (255, 255, 255)])

    replaced = vector_processing.replace_krasnow_black_layer(
        {"#0000FF": blue, "#000000": old_black},
        "#000000",
        source,
    )

    assert replaced["#0000FF"] is blue
    assert replaced["#000000"].equals(box(0, 0, 1, 1))


def test_krasnow_black_cutoff_is_strictly_below_lightburn_teal():
    source = Image.new("RGB", (3, 1))
    source.putdata([(0, 70, 84), (0, 71, 84), (0, 72, 84)])

    mask = vector_processing.source_black_cutoff_mask(source)

    assert mask.tolist() == [[True, False, False]]


def test_nonblack_krasnow_palette_cannot_introduce_black(tmp_path):
    source = Image.new("RGB", (3, 1))
    source.putdata([(1, 1, 1), (5, 0, 0), (0, 0, 5)])
    source_path = tmp_path / "dark-source.png"
    source.save(source_path)

    quantized = vector_processing.prepare_raster_image(
        raster_image_path=source_path,
        new_height=0,
        new_width=3,
        quantize_colors=2,
        target_colors={"#A00000": (), "#0000A0": ()},
        prevent_palette_black=True,
    )

    pixels = {tuple(pixel) for pixel in np.asarray(quantized).reshape(-1, 3)}
    assert (0, 0, 0) not in pixels
    assert pixels <= {(160, 0, 0), (0, 0, 160)}

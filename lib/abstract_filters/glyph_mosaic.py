"""Image-driven glyph mosaic built on Halftone Newsprint's shared matrix."""

from .common import number
from . import halftone_newsprint


USES_SOURCE_LUMINANCE = True
PRESERVE_SOURCE_BLACK = True

GLYPH_SHAPES = {
    "circle", "square", "diamond", "triangle", "hexagon", "octagon",
    "star", "cross", "bar", "mixed",
}

DEFAULTS = {
    "glyph_shape": "diamond",
    "cell_size_mm": 0.6,
    "minimum_glyph_ratio": 0.48,
    "maximum_glyph_ratio": 0.97,
    "non_black_glyph_density": 2.3,
    "tone_curve": 0.75,
    "contrast": 2.0,
    "grid_angle": -45.0,
    "glyph_rotation": 0.0,
    "invert": 0,
    "black_only": 0,
    "seed": 1,
}

VECTOR_DEFAULTS = dict(halftone_newsprint.VECTOR_DEFAULTS)

CONTROLS = (
    ("cell_size_mm", 0.2, 1.0, 0.05),
    ("minimum_glyph_ratio", 0.16, 0.8, 0.01),
    ("maximum_glyph_ratio", 0.94, 1.0, 0.01),
    ("non_black_glyph_density", 0.6, 4.0, 0.05),
    ("tone_curve", 0.2, 1.3, 0.05),
    ("contrast", 1.0, 3.0, 0.05),
    ("grid_angle", -90, 0, 1),
    ("glyph_rotation", -180, 180, 1),
    ("invert", 0, 1, 1),
    ("black_only", 0, 1, 1),
    ("seed", 0, 999999, 1),
)


def apply(geometry, settings):
    return geometry


def remap_layers(processed_layers, target_colors, settings):
    shape = str(settings.get("glyph_shape") or DEFAULTS["glyph_shape"]).strip().lower()
    if shape not in GLYPH_SHAPES:
        raise ValueError(f"Glyph Mosaic shape '{shape}' is not supported.")
    translated = dict(settings)
    translated.update({
        "minimum_dot_ratio": number(
            settings.get("minimum_glyph_ratio"), DEFAULTS["minimum_glyph_ratio"], 0, 0.8
        ),
        "maximum_dot_ratio": number(
            settings.get("maximum_glyph_ratio"), DEFAULTS["maximum_glyph_ratio"], 0.1, 1
        ),
        "non_black_dot_density": number(
            settings.get("non_black_glyph_density"), DEFAULTS["non_black_glyph_density"], 0.25, 4
        ),
        "_glyph_shape": shape,
        "_glyph_rotation": number(settings.get("glyph_rotation"), 0, -180, 180),
        "_glyph_seed": number(settings.get("seed"), 1, 0, 999999),
        "_progress_name": "Glyph Mosaic",
    })
    return halftone_newsprint.remap_layers(processed_layers, target_colors, translated)

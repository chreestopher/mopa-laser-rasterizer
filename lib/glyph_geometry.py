"""Shared glyph renderer used by Rasterizer Geometry Styles."""

from abstract_filters.common import number
from abstract_filters import halftone_newsprint


USES_SOURCE_LUMINANCE = True
PRESERVE_SOURCE_BLACK = True

GLYPH_SHAPES = {
    "circle", "square", "diamond", "triangle", "hexagon", "octagon",
    "star", "cross", "bar", "skull", "heart", "space_invader", "ghost",
    "bat", "alien_head", "paw_print", "fish_scale", "puzzle_piece", "mixed",
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


def remap_layers(processed_layers, target_colors, settings):
    shape = str(settings.get("glyph_shape") or DEFAULTS["glyph_shape"]).strip().lower()
    if shape not in GLYPH_SHAPES:
        raise ValueError(f"Glyph Geometry shape '{shape}' is not supported.")
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
        "_progress_name": settings.get("_progress_name") or "Glyph Geometry Style",
    })
    return halftone_newsprint.remap_layers(processed_layers, target_colors, translated)

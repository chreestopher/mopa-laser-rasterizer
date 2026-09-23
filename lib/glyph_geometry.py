"""Shared glyph renderer used by Rasterizer Geometry Styles."""

from abstract_filters.common import number
from abstract_filters import halftone_newsprint
from custom_shape import mask_to_unit_geometry, svg_to_unit_geometry


USES_SOURCE_LUMINANCE = True
PRESERVE_SOURCE_BLACK = True

GLYPH_SHAPES = {
    "circle", "square", "diamond", "triangle", "hexagon", "octagon",
    "star", "cross", "bar", "skull", "heart", "space_invader", "ghost",
    "bat", "alien_head", "paw_print", "fish_scale", "puzzle_piece", "mixed",
    "custom",
}

DEFAULTS = {
    "glyph_shape": "diamond",
    "glyph_size_source": "source_brightness",
    "cell_size_mm": 0.6,
    "minimum_glyph_ratio": 0.48,
    "maximum_glyph_ratio": 0.97,
    "non_black_glyph_density": 2.3,
    "tone_curve": 0.75,
    "contrast": 2.0,
    "grid_angle": -45.0,
    "glyph_rotation": 0.0,
    "tight_pack_geometry": 0,
    "random_rotation": 0,
    "custom_glyph_threshold": 0.5,
    "custom_glyph_invert": 0,
    "custom_glyph_padding": 0.06,
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
    size_source = str(
        settings.get("glyph_size_source") or DEFAULTS["glyph_size_source"]
    ).strip().lower()
    if size_source not in {"source_brightness", "seeded_variation"}:
        raise ValueError(
            f"Glyph Geometry size source '{size_source}' is not supported."
        )
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
        "_glyph_size_source": size_source,
        "_preserve_dot_ratio_range": 1,
        "_glyph_rotation": number(settings.get("glyph_rotation"), 0, -180, 180),
        "_tight_pack_geometry": number(settings.get("tight_pack_geometry"), 0, 0, 1),
        "_random_rotation": number(settings.get("random_rotation"), 0, 0, 1),
        "_glyph_seed": number(settings.get("seed"), 1, 0, 999999),
        "_progress_name": settings.get("_progress_name") or "Glyph Geometry Style",
    })
    if shape == "custom":
        padding = number(settings.get("custom_glyph_padding"), 0.06, 0, 0.3)
        if settings.get("custom_glyph_svg"):
            translated["_custom_glyph_template"] = svg_to_unit_geometry(
                settings.get("custom_glyph_svg"), padding=padding
            )
        else:
            translated["_custom_glyph_template"] = mask_to_unit_geometry(
                settings.get("custom_glyph_mask"),
                threshold=number(settings.get("custom_glyph_threshold"), 0.5, 0, 1),
                invert=bool(settings.get("custom_glyph_invert")),
                padding=padding,
            )
    return halftone_newsprint.remap_layers(processed_layers, target_colors, translated)

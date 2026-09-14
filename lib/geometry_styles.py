"""Optional final geometry renderers shared by ordinary Rasterizer presets."""

from abstract_filters import krasnow_grating
import glyph_geometry
from shapely.geometry import GeometryCollection, box


GLYPH_STYLE = "glyphs"
KRASNOW_STYLE = "krasnow_grating"
ROUTED_STYLE = "by_swatch"
NORMAL_STYLE = "vectors"
SUPPORTED_STYLES = {NORMAL_STYLE, GLYPH_STYLE, KRASNOW_STYLE, ROUTED_STYLE}
SPECIALIZED_FILTERS = {
    "halftone_newsprint", "optical_color_mix", "krasnow_grating",
}


def normalize(style, parameters=None, abstract_filter="none"):
    style = str(style or NORMAL_STYLE).strip().lower()
    if style not in SUPPORTED_STYLES:
        raise ValueError(f"Geometry style '{style}' is not supported.")
    filter_name = str(abstract_filter or "none").strip().lower()
    if style in {GLYPH_STYLE, KRASNOW_STYLE, ROUTED_STYLE} and filter_name in SPECIALIZED_FILTERS:
        raise ValueError(
            f"{style_label(style)} Geometry Style is not available with Halftone "
            "Newsprint, Optical Color Mix, or Krasnow Grating."
        )
    if style == NORMAL_STYLE:
        return style, {}
    if style == ROUTED_STYLE:
        raw = dict(parameters or {})
        raw_assignments = raw.get("assignments") or {}
        if not isinstance(raw_assignments, dict) or len(raw_assignments) > 64:
            raise ValueError("Geometry routing assignments must be a small object.")
        assignments = {}
        for color_hex, assigned_style in raw_assignments.items():
            color_hex = str(color_hex).strip().upper()
            assigned_style = str(assigned_style).strip().lower()
            if (
                len(color_hex) != 7
                or not color_hex.startswith("#")
                or any(character not in "0123456789ABCDEF" for character in color_hex[1:])
                or assigned_style not in {NORMAL_STYLE, GLYPH_STYLE, KRASNOW_STYLE}
            ):
                raise ValueError("Geometry routing contains an invalid swatch assignment.")
            assignments[color_hex] = assigned_style
        # Mixed routing keeps Black as the mutually-exclusive vector mask. This
        # prevents transformed non-Black regions from being engraved over a
        # second Black treatment.
        assignments["#000000"] = NORMAL_STYLE
        normalized = {"assignments": assignments}
        used_styles = set(assignments.values())
        if GLYPH_STYLE in used_styles:
            _, glyph_parameters = normalize(
                GLYPH_STYLE, raw.get(GLYPH_STYLE) or {}, filter_name
            )
            glyph_parameters["black_only"] = 0
            normalized[GLYPH_STYLE] = glyph_parameters
        if KRASNOW_STYLE in used_styles:
            _, krasnow_parameters = normalize(
                KRASNOW_STYLE, raw.get(KRASNOW_STYLE) or {}, filter_name
            )
            normalized[KRASNOW_STYLE] = krasnow_parameters
        normalized.update({key: value for key, value in raw.items() if str(key).startswith("_")})
        return style, normalized
    defaults = (
        krasnow_grating.DEFAULTS if style == KRASNOW_STYLE
        else glyph_geometry.DEFAULTS
    )
    values = dict(defaults)
    values.update(parameters or {})
    # Ignore the retired posterization experiment defensively. The request
    # parsers also remove it, but workers may receive jobs queued by an older
    # API or browser revision during a rolling staging deployment.
    values.pop("posterize_colors", None)
    if bool(values.get("invert_fill")) and bool(values.get("black_only")):
        raise ValueError("Invert Fill cannot be combined with Black Only.")
    return style, values


def style_label(style):
    style = str(style or NORMAL_STYLE).strip().lower()
    if style == ROUTED_STYLE:
        return "Geometry Routing"
    return (
        "Krasnow Grating"
        if style == KRASNOW_STYLE
        else "Glyph"
    )


def module_for_style(style):
    style = str(style or NORMAL_STYLE).strip().lower()
    if style == KRASNOW_STYLE:
        return krasnow_grating
    if style == GLYPH_STYLE:
        return glyph_geometry
    return None


def assigned_styles(style, parameters=None):
    """Return the concrete renderers used by a uniform or routed style."""
    style = str(style or NORMAL_STYLE).strip().lower()
    if style != ROUTED_STYLE:
        return {style}
    return set((parameters or {}).get("assignments", {}).values()) or {NORMAL_STYLE}


def parameters_for_style(style, parameters, requested_style):
    """Return one concrete renderer's settings from a normalized selection."""
    if str(style or NORMAL_STYLE).strip().lower() == ROUTED_STYLE:
        return dict((parameters or {}).get(requested_style) or {})
    return dict(parameters or {}) if style == requested_style else {}


def target_colors_for_style(target_colors, parameters, requested_style):
    assignments = (parameters or {}).get("assignments", {})
    return {
        color_hex: metadata
        for color_hex, metadata in target_colors.items()
        if assignments.get(str(color_hex).upper(), NORMAL_STYLE) == requested_style
    }


def vector_settings_for_style(style, parameters=None):
    """Return preprocessing overrides owned only by the selected style."""
    return {}


def preserves_source_black(style, parameters=None):
    style = str(style or NORMAL_STYLE).strip().lower()
    if style == ROUTED_STYLE:
        return bool(assigned_styles(style, parameters) - {NORMAL_STYLE})
    if style == GLYPH_STYLE:
        return True
    if style == KRASNOW_STYLE:
        return krasnow_grating._preserve_black(parameters or {})
    return False


def uses_source_luminance(style, parameters=None):
    return bool(assigned_styles(style, parameters) & {GLYPH_STYLE, KRASNOW_STYLE})


def _exclusive_source_layers(processed_layers, target_colors, bounds):
    """Give every transformed point one deterministic source-layer owner."""
    canvas = box(*bounds)
    occupied = GeometryCollection()
    output = {}
    ordered_colors = [
        color_hex
        for color_hex, _ in sorted(
            target_colors.items(), key=lambda item: item[1][1]
        )
    ]
    ordered_colors.extend(
        color_hex for color_hex in processed_layers if color_hex not in target_colors
    )
    for color_hex in ordered_colors:
        geometry = processed_layers.get(color_hex)
        if geometry is None or geometry.is_empty:
            continue
        owned = geometry.intersection(canvas)
        if not occupied.is_empty:
            owned = owned.difference(occupied)
        if owned.is_empty:
            continue
        output[color_hex] = owned
        occupied = occupied.union(owned)
    return output


def apply(processed_layers, target_colors, style, parameters=None, abstract_filter="none"):
    style, values = normalize(style, parameters, abstract_filter)
    if style == NORMAL_STYLE:
        return processed_layers
    if style == ROUTED_STYLE:
        bounds = values.get("_canvas_bounds")
        if bounds and len(bounds) == 4:
            processed_layers = _exclusive_source_layers(
                processed_layers, target_colors, bounds
            )
        assignments = values["assignments"]
        routed_layers = {NORMAL_STYLE: {}, GLYPH_STYLE: {}, KRASNOW_STYLE: {}}
        for color_hex, geometry in processed_layers.items():
            assigned_style = assignments.get(str(color_hex).upper(), NORMAL_STYLE)
            routed_layers[assigned_style][color_hex] = geometry

        output = dict(routed_layers[NORMAL_STYLE])
        for routed_style, renderer in (
            (GLYPH_STYLE, glyph_geometry.remap_layers),
            (KRASNOW_STYLE, krasnow_grating.remap_layers),
        ):
            source_layers = routed_layers[routed_style]
            if not source_layers:
                continue
            routed_parameters = dict(values.get(routed_style) or {})
            for private_name in (
                "_canvas_bounds", "_scale_factor", "_angle_image", "_progress_logger"
            ):
                if private_name in values:
                    routed_parameters[private_name] = values[private_name]
            routed_parameters["_progress_name"] = (
                "Routed Glyph Geometry"
                if routed_style == GLYPH_STYLE
                else "Routed Krasnow Grating Geometry"
            )
            routed_targets = target_colors_for_style(
                target_colors, values, routed_style
            )
            output.update(renderer(source_layers, routed_targets, routed_parameters))
        return output
    if style == KRASNOW_STYLE:
        values["_progress_name"] = "Krasnow Grating Geometry Style"
        bounds = values.get("_canvas_bounds")
        if bounds and len(bounds) == 4:
            processed_layers = _exclusive_source_layers(
                processed_layers, target_colors, bounds
            )
        return krasnow_grating.remap_layers(processed_layers, target_colors, values)
    values["_progress_name"] = "Glyph Geometry Style"
    return glyph_geometry.remap_layers(processed_layers, target_colors, values)

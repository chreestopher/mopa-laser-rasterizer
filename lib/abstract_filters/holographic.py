"""Calibration-free holographic grating treatment.

The selected light swatches retain their recognizable source geometry.  The
Holographic Material Library setting supplies the Fill/Scan grating itself,
just as a single recipe does in the Holographic Etching Lab.
"""

# The vector pipeline uses these declarations to preserve dark artwork while
# applying the dedicated holographic setting to light/background swatches.
LIGHT_LAYERS_ONLY = True
PRESERVE_BLACK_CANVAS = True
PUNCH_SOURCE_GEOMETRY = True
SETTING_NAME_PARAMETER = "setting_name"
KEEP_SOURCE_BLACK_PARAMETER = "keep_black"
RASTER_RECTANGLE_MODE = True
HOLOGRAPHIC_COLOR = "#7A00FF"

DEFAULTS = {
    "setting_name": "holographic",
    "light_threshold": 150,
    "invert_threshold": False,
    "keep_black": False,
    "fill_mode": "from_setting",
}

CONTROLS = (
    ("light_threshold", 0, 255, 1),
)


def apply(geometry, settings):
    """Keep the selected image region intact for a continuous scan grating."""
    return geometry

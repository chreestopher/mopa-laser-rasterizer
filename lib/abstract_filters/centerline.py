"""Image-to-line-art preparation for the Centerline Drawing preset."""

import cv2
import numpy as np
from shapely.geometry import box
from shapely.ops import unary_union

from .common import number


DEFAULTS = {
    "dark_threshold": 145,
    "contrast": 1.15,
    "blur": 1.0,
    "gap_closure": 1,
    "line_simplification": .35,
    "min_branch_length": 8,
    "stroke_width": .35,
}
CONTROLS = (
    ("dark_threshold", 20, 245, 1),
    ("contrast", .3, 3, .05),
    ("blur", 0, 5, .25),
    ("gap_closure", 0, 3, 1),
    ("line_simplification", 0, 3, .05),
    ("min_branch_length", 0, 80, 1),
    ("stroke_width", .05, 4, .05),
)


def line_art_boxes(image, settings):
    """Turn only dark source-image outlines into raster cells.

    The normal color pipeline starts with filled quantized regions, which is
    useful for color engraving but fundamentally wrong for line art.  This
    selects dark ink from image luminance before the shared path tracer
    reduces it to clean open laser paths.  Bright or saturated color edges
    are deliberately ignored unless they are also dark enough to read as ink.
    """
    grayscale = np.asarray(image.convert("L"), dtype=np.uint8)
    blur = number(settings.get("blur"), 1.0, 0, 5)
    if blur:
        kernel = max(3, int(round(blur * 4)) | 1)
        softened = cv2.GaussianBlur(grayscale, (kernel, kernel), blur)
    else:
        softened = grayscale

    contrast = number(settings.get("contrast"), 1.15, .3, 3)
    adjusted = np.clip((softened.astype(np.float32) - 127.5) * contrast + 127.5, 0, 255).astype(np.uint8)
    dark_threshold = int(round(number(settings.get("dark_threshold"), 145, 20, 245)))
    _, ink = cv2.threshold(adjusted, dark_threshold, 255, cv2.THRESH_BINARY_INV)

    # Close tiny breaks in hand-drawn or compressed outlines without joining
    # neighboring shapes.  Zero leaves every original gap untouched.
    gap_closure = int(round(number(settings.get("gap_closure"), 1, 0, 3)))
    if gap_closure:
        kernel_size = gap_closure * 2 + 1
        ink = cv2.morphologyEx(
            ink, cv2.MORPH_CLOSE,
            np.ones((kernel_size, kernel_size), dtype=np.uint8),
        )
    y_values, x_values = np.nonzero(ink)
    return [box(int(x), int(y), int(x) + 1, int(y) + 1) for y, x in zip(y_values, x_values)]


# Centerline consumes prepared line-art cells rather than finalized polygons.
def process_boxes(boxes, settings, skeletonizer):
    centerlines = skeletonizer(boxes, settings)
    if centerlines.is_empty:
        return centerlines

    # Laser fill workflows and the Lightburn punch-through pipeline expect
    # closed shapes.  Buffer each central stroke into a narrow, round-capped
    # ribbon, keeping it visually centered without exporting open paths or
    # forcing the laser to retrace every line back to its start.
    stroke_width = number(settings.get("stroke_width"), .35, .05, 4)
    ribbons = [
        line.buffer(stroke_width / 2, cap_style=1, join_style=1)
        for line in getattr(centerlines, "geoms", (centerlines,))
        if not line.is_empty and len(line.coords) >= 2
    ]
    return unary_union(ribbons) if ribbons else centerlines.buffer(0)

"""Validated compact grayscale masks shared by custom geometry features."""

import base64
import binascii

import cv2
import numpy as np
from shapely.affinity import affine_transform
from shapely.geometry import GeometryCollection, Polygon
from shapely.ops import unary_union


MAX_MASK_DIMENSION = 128
MAX_MASK_BYTES = MAX_MASK_DIMENSION * MAX_MASK_DIMENSION


def decode_grayscale_mask(spec):
    """Decode a browser-normalized 8-bit mask after strict size validation."""
    if not isinstance(spec, dict):
        raise ValueError("Custom shape mask must be an object.")
    try:
        width = int(spec.get("width"))
        height = int(spec.get("height"))
    except (TypeError, ValueError):
        raise ValueError("Custom shape mask dimensions are invalid.") from None
    if not 8 <= width <= MAX_MASK_DIMENSION or not 8 <= height <= MAX_MASK_DIMENSION:
        raise ValueError(
            f"Custom shape masks must be between 8 and {MAX_MASK_DIMENSION} pixels per side."
        )
    encoded = spec.get("data")
    if not isinstance(encoded, str) or len(encoded) > ((MAX_MASK_BYTES + 2) // 3) * 4 + 8:
        raise ValueError("Custom shape mask data is invalid.")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("Custom shape mask data is invalid.") from None
    if len(raw) != width * height:
        raise ValueError("Custom shape mask data does not match its dimensions.")
    return np.frombuffer(raw, dtype=np.uint8).reshape((height, width))


def _contour_points(contour, width, height):
    denominator_x = max(width - 1, 1)
    denominator_y = max(height - 1, 1)
    return [
        (
            float(point[0][0]) / denominator_x - 0.5,
            0.5 - float(point[0][1]) / denominator_y,
        )
        for point in contour
    ]


def mask_to_unit_geometry(spec, threshold=0.5, invert=False, padding=0.06):
    """Trace a normalized mask into one reusable Shapely glyph template."""
    image = decode_grayscale_mask(spec)
    clean_threshold = min(1.0, max(0.0, float(threshold)))
    binary = image >= round(clean_threshold * 255)
    if invert:
        binary = ~binary
    if not np.any(binary):
        raise ValueError("The custom glyph mask is empty at the selected threshold.")

    contours, hierarchy = cv2.findContours(
        binary.astype(np.uint8) * 255,
        cv2.RETR_CCOMP,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    hierarchy = hierarchy[0] if hierarchy is not None else []
    polygons = []
    for index, contour in enumerate(contours):
        if len(hierarchy) and hierarchy[index][3] != -1:
            continue
        contour = cv2.approxPolyDP(contour, 0.75, True)
        shell = _contour_points(contour, image.shape[1], image.shape[0])
        if len(shell) < 3:
            continue
        holes = []
        child = hierarchy[index][2] if len(hierarchy) else -1
        while child != -1:
            hole = cv2.approxPolyDP(contours[child], 0.75, True)
            points = _contour_points(hole, image.shape[1], image.shape[0])
            if len(points) >= 3:
                holes.append(points)
            child = hierarchy[child][0]
        polygon = Polygon(shell, holes)
        if not polygon.is_empty and polygon.area > 0:
            polygons.append(polygon)
    geometry = unary_union(polygons).buffer(0) if polygons else GeometryCollection()
    if geometry.is_empty:
        raise ValueError("The custom glyph mask did not contain a usable silhouette.")

    min_x, min_y, max_x, max_y = geometry.bounds
    width = max_x - min_x
    height = max_y - min_y
    if width <= 0 or height <= 0:
        raise ValueError("The custom glyph mask did not contain a usable silhouette.")
    clean_padding = min(0.3, max(0.0, float(padding)))
    scale = (1.0 - clean_padding * 2.0) / max(width, height)
    center_x = (min_x + max_x) / 2.0
    center_y = (min_y + max_y) / 2.0
    return affine_transform(
        geometry,
        (scale, 0, 0, scale, -center_x * scale, -center_y * scale),
    )

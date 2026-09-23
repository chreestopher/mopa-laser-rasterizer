"""Validated compact grayscale masks shared by custom geometry features."""

import base64
import binascii
from io import StringIO
import re

import cv2
import numpy as np
from shapely.affinity import affine_transform
from shapely.geometry import GeometryCollection, Polygon
from shapely.ops import unary_union
from svgelements import Close, Move, Path, Shape, SVG


MAX_MASK_DIMENSION = 128
MAX_MASK_BYTES = MAX_MASK_DIMENSION * MAX_MASK_DIMENSION
MAX_SVG_CHARACTERS = 65_536
MAX_SVG_POINTS = 4_096


def _normalize_unit_geometry(geometry, padding, *, flip_y=True, empty_message=None):
    geometry = geometry.buffer(0)
    if geometry.is_empty:
        raise ValueError(empty_message or "The custom vector SVG did not contain a usable closed shape.")
    min_x, min_y, max_x, max_y = geometry.bounds
    width = max_x - min_x
    height = max_y - min_y
    if width <= 0 or height <= 0:
        raise ValueError(empty_message or "The custom vector SVG did not contain a usable closed shape.")
    clean_padding = min(0.3, max(0.0, float(padding)))
    scale = (1.0 - clean_padding * 2.0) / max(width, height)
    center_x = (min_x + max_x) / 2.0
    center_y = (min_y + max_y) / 2.0
    return affine_transform(
        geometry,
        (
            scale,
            0,
            0,
            -scale if flip_y else scale,
            -center_x * scale,
            center_y * scale if flip_y else -center_y * scale,
        ),
    )


def _validate_svg_text(svg_text):
    if not isinstance(svg_text, str) or not svg_text.strip():
        raise ValueError("The custom vector SVG is empty.")
    if len(svg_text) > MAX_SVG_CHARACTERS:
        raise ValueError(
            f"Custom vector SVG files must be no larger than {MAX_SVG_CHARACTERS // 1024} KB."
        )
    lowered = svg_text.lower()
    if any(token in lowered for token in (
        "<!doctype", "<!entity", "<script", "<foreignobject", "<image",
        "<use", "javascript:", "data:", "url(", "href=", "xlink:href=",
    )):
        raise ValueError(
            "The custom vector SVG contains embedded or external content. "
            "Use an SVG made only from closed vector shapes."
        )
    if not re.search(r"<svg(?:\s|>)", lowered):
        raise ValueError("The uploaded file is not an SVG document.")
    return svg_text


def _sample_closed_subpath(subpath, remaining_points):
    segments = list(subpath)
    drawable = [segment for segment in segments if not isinstance(segment, Move)]
    if not drawable:
        return None, remaining_points
    first = drawable[0].start
    last = drawable[-1].end
    explicitly_closed = isinstance(drawable[-1], Close)
    geometrically_closed = (
        (float(last.x) - float(first.x)) ** 2
        + (float(last.y) - float(first.y)) ** 2
    ) ** 0.5 <= 1e-7
    if not explicitly_closed and not geometrically_closed:
        return None, remaining_points

    points = [(float(first.x), float(first.y))]
    for segment in drawable:
        name = type(segment).__name__
        steps = 1 if name in {"Line", "Close"} else 12
        for step in range(1, steps + 1):
            point = segment.point(step / steps)
            points.append((float(point.x), float(point.y)))
            remaining_points -= 1
            if remaining_points < 0:
                raise ValueError(
                    f"Custom vector SVG shapes may contain at most {MAX_SVG_POINTS:,} sampled points."
                )
    if len(points) < 4:
        return None, remaining_points
    return Polygon(points), remaining_points


def svg_to_unit_geometry(spec, padding=0.06):
    """Parse a safe SVG into one normalized reusable vector template."""
    if not isinstance(spec, dict):
        raise ValueError("Custom vector SVG data must be an object.")
    svg_text = _validate_svg_text(spec.get("svg"))
    try:
        document = SVG.parse(StringIO(svg_text))
    except Exception as error:
        raise ValueError(
            "The custom vector SVG could not be read. Export it as a plain SVG "
            "containing closed paths and try again."
        ) from error

    rings = []
    remaining_points = MAX_SVG_POINTS
    for element in document.elements():
        if not isinstance(element, Shape):
            continue
        try:
            path = Path(element)
        except Exception:
            continue
        for subpath in path.as_subpaths():
            polygon, remaining_points = _sample_closed_subpath(
                subpath, remaining_points
            )
            if polygon is not None and not polygon.is_empty and polygon.area > 1e-12:
                rings.append(polygon.buffer(0))
    if not rings:
        raise ValueError(
            "The custom vector SVG does not contain a closed shape. Close at "
            "least one path in your vector editor and export the SVG again."
        )

    # SVG glyphs commonly express holes as nested subpaths. Applying even-odd
    # nesting here preserves those counters without retaining any SVG styling.
    ordered = sorted(rings, key=lambda item: item.area, reverse=True)
    geometry = GeometryCollection()
    for index, ring in enumerate(ordered):
        marker = ring.representative_point()
        depth = sum(parent.contains(marker) for parent in ordered[:index])
        geometry = geometry.difference(ring) if depth % 2 else unary_union((geometry, ring))
    # Rasterizer's image-derived geometry and exported SVG coordinates both
    # increase downward. Preserve the uploaded SVG's visual orientation so an
    # asymmetric custom glyph or Krasnow cell is not turned upside down.
    return _normalize_unit_geometry(geometry, padding, flip_y=False)


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

    # Raster masks already use an upward-positive coordinate conversion, so
    # retain their established orientation instead of applying the SVG flip.
    return _normalize_unit_geometry(
        geometry,
        padding,
        flip_y=False,
        empty_message="The custom glyph mask did not contain a usable silhouette.",
    )

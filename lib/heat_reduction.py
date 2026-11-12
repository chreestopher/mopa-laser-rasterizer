"""Partition finalized engraving geometry without moving or duplicating it."""

import json
import math


def normalize_heat_reduction(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            raise ValueError("Heat Reduction settings could not be read.") from None
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError("Heat Reduction settings could not be read.")
    enabled = str(value.get("enabled", False)).strip().lower() in {"true", "1", "yes", "on"}
    if not enabled:
        return {"enabled": False}
    raw = value.get("projects", 4)
    try:
        count = float(raw)
        if isinstance(raw, bool) or not math.isfinite(count) or not count.is_integer() or not 2 <= count <= 10:
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        raise ValueError("Heat Reduction requires a whole number of projects from 2 to 10.") from None
    return {"enabled": True, "projects": int(count)}


def geometry_units(geometry):
    if geometry.is_empty:
        return
    if hasattr(geometry, "geoms"):
        for part in geometry.geoms:
            yield from geometry_units(part)
    elif geometry.geom_type in {"Polygon", "LineString", "LinearRing"}:
        yield geometry


def distribute_layers(layers, count, interleaved_colors=()):
    """Keep polygons (including holes) intact; interleave individual strokes.

    Krasnow already produces individual open strokes. Round-robin assignment
    in spatial order separates neighboring strokes without cutting them. Filled
    components use largest-first area balancing, with spatially varied ties.
    """
    from shapely.geometry import GeometryCollection

    jobs = [dict() for _ in range(count)]
    areas = [0.0] * count
    polygons, lines = [], []
    for color, geometry in layers.items():
        for unit in geometry_units(geometry):
            (polygons if unit.geom_type == "Polygon" and color not in interleaved_colors else lines).append((color, unit))
    polygons.sort(key=lambda item: (-item[1].area, item[1].centroid.y, item[1].centroid.x, item[0]))
    for ordinal, (color, unit) in enumerate(polygons):
        # Vary ties so rows of equal shapes do not repeatedly start in one job.
        preferred = (ordinal * 7 + ordinal // count) % count
        index = min(range(count), key=lambda i: (areas[i], (i - preferred) % count))
        jobs[index].setdefault(color, []).append(unit)
        areas[index] += unit.area
    lines.sort(key=lambda item: (item[1].centroid.y, item[1].centroid.x, item[0]))
    for ordinal, (color, unit) in enumerate(lines):
        jobs[ordinal % count].setdefault(color, []).append(unit)
    return [
        {color: GeometryCollection(parts) for color, parts in job.items()}
        for job in jobs
    ]

"""Deterministic layered mandala geometry and export helpers."""

from __future__ import annotations

import json
import math
import os
import zipfile
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree as ET

from shapely import affinity
from shapely.geometry import GeometryCollection, LineString, Point, Polygon
from shapely.ops import unary_union

from lib import lightburn
from lib.custom_shape import svg_to_unit_geometry


MANDALA_LAYER_LIMIT = 12
BUILTIN_MOTIFS = {"petal", "leaf", "diamond", "circle", "triangle", "star", "heart"}
SUPPORT_MODES = {"outer_rim", "automatic_bridges", "fully_connected", "loose"}
CONSTRUCTION_MODES = {"cutout", "positive"}
RIM_STYLES = {"closed", "petal", "open"}
ORNAMENT_STYLES = {"lotus", "billow", "paisley", "rose_lace", "leaf_lace"}
LAYER_COLORS = (
    "#E44D61", "#F39C49", "#E4D354", "#72C66A", "#43B7A7", "#4C9DDE",
    "#6C70D8", "#9B63C7", "#D05AA8", "#BC7C58", "#8B9A52", "#5E8792",
)


def _number(value, name, minimum, maximum):
    try:
        value = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be a number") from error
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum:g} and {maximum:g}")
    return value


def _integer(value, name, minimum, maximum):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a whole number")
    try:
        integer = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be a whole number") from error
    if str(value).strip() not in {str(integer), f"{integer}.0"} or not minimum <= integer <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return integer


def _boolean(value, name, default):
    value = default if value is None else value
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be on or off")
    return value


def validate_mandala_config(raw):
    """Return a compact, validated configuration suitable for a worker payload."""
    if not isinstance(raw, dict):
        raise ValueError("Layered Mandala settings could not be read")
    name = str(raw.get("project_name") or "Layered Mandala").strip()[:120]
    if not name:
        raise ValueError("Enter a project name")
    diameter = _number(raw.get("diameter_mm", 150), "Finished diameter", 20, 1000)
    workbed_width = _number(raw.get("workbed_width_mm", diameter), "Workbed width", diameter, 3000)
    workbed_height = _number(raw.get("workbed_height_mm", diameter), "Workbed height", diameter, 3000)
    layers = raw.get("layers")
    if not isinstance(layers, list) or not 1 <= len(layers) <= MANDALA_LAYER_LIMIT:
        raise ValueError(f"A Layered Mandala needs 1 to {MANDALA_LAYER_LIMIT} layers")
    custom_svg_characters = 0
    cleaned_layers = []
    for index, source in enumerate(layers, start=1):
        if not isinstance(source, dict):
            raise ValueError(f"Mandala layer {index} could not be read")
        motif = str(source.get("motif") or "petal").strip().lower()
        custom_svg = source.get("custom_svg")
        if motif == "custom":
            if not isinstance(custom_svg, dict):
                raise ValueError(f"Mandala layer {index} needs a custom SVG motif")
            svg_text = custom_svg.get("svg")
            if not isinstance(svg_text, str):
                raise ValueError(f"Mandala layer {index}'s custom SVG could not be read")
            custom_svg_characters += len(svg_text)
            # Parse now so invalid or unsafe SVGs fail before geometry generation.
            svg_to_unit_geometry(custom_svg, padding=0.04)
            cleaned_svg = {
                "name": str(custom_svg.get("name") or f"layer-{index}-motif.svg")[:120],
                "svg": svg_text,
            }
        elif motif in BUILTIN_MOTIFS:
            cleaned_svg = None
        else:
            raise ValueError(f"Mandala layer {index} uses an unsupported motif")
        construction = str(source.get("construction") or "cutout").strip().lower()
        support = str(source.get("support_mode") or "automatic_bridges").strip().lower()
        rim_style = str(source.get("rim_style") or "closed").strip().lower()
        if construction not in CONSTRUCTION_MODES:
            raise ValueError(f"Mandala layer {index} has an invalid construction mode")
        if support not in SUPPORT_MODES:
            raise ValueError(f"Mandala layer {index} has an invalid structural support mode")
        if rim_style not in RIM_STYLES:
            raise ValueError(f"Mandala layer {index} has an invalid outer edge style")
        ornament_style = str(source.get("ornament_style") or "lotus").strip().lower()
        if ornament_style not in ORNAMENT_STYLES:
            raise ValueError(f"Mandala layer {index} has an invalid ornament family")
        cleaned_layers.append({
            "name": str(source.get("name") or f"Layer {index}").strip()[:80] or f"Layer {index}",
            "motif": motif,
            "custom_svg": cleaned_svg,
            "construction": construction,
            "support_mode": support,
            "rim_style": rim_style,
            "ornament_style": ornament_style,
            "repetitions": _integer(source.get("repetitions", 12), f"Layer {index} repetitions", 4, 32),
            "rings": _integer(source.get("rings", 3), f"Layer {index} rings", 1, 8),
            "inner_radius_ratio": _number(source.get("inner_radius_ratio", 0.18), f"Layer {index} inner radius", 0.05, 0.55),
            "motif_scale": _number(source.get("motif_scale", 0.72), f"Layer {index} motif scale", 0.2, 0.95),
            "radial_stretch": _number(source.get("radial_stretch", 1), f"Layer {index} radial stretch", 0.4, 1.8),
            "tangent_stretch": _number(source.get("tangent_stretch", 1), f"Layer {index} tangent stretch", 0.4, 1.8),
            "twist_degrees": _number(source.get("twist_degrees", 18), f"Layer {index} twist", -180, 180),
            "rotation_degrees": _number(source.get("rotation_degrees", 0), f"Layer {index} rotation", -180, 180),
            "alternate_rotation": _boolean(source.get("alternate_rotation"), f"Layer {index} alternate ring phase", True),
            "mirror_alternating": _boolean(source.get("mirror_alternating"), f"Layer {index} mirror alternating motifs", False),
            "rim_width_mm": _number(source.get("rim_width_mm", max(2, diameter * 0.025)), f"Layer {index} rim width", 0.5, diameter * 0.15),
            "bridge_width_mm": _number(source.get("bridge_width_mm", max(1, diameter * 0.012)), f"Layer {index} bridge width", 0.4, diameter * 0.08),
            "support_sweep_degrees": _number(source.get("support_sweep_degrees", 0), f"Layer {index} support sweep", -75, 75),
            "bridge_wave_amount": _number(source.get("bridge_wave_amount", 0), f"Layer {index} bridge wave amount", 0, 1),
            "bridge_wave_amplitude_mm": _number(source.get("bridge_wave_amplitude_mm", max(2, diameter * 0.04)), f"Layer {index} bridge wave amplitude", 0, diameter * 0.2),
            "bridge_wave_position": _number(source.get("bridge_wave_position", 0.5), f"Layer {index} bridge wave position", 0.1, 0.9),
            "layer_openness": _number(source.get("layer_openness", 0), f"Layer {index} openness", 0, 1),
            "opening_inner_ratio": _number(source.get("opening_inner_ratio", 0.25), f"Layer {index} opening inner position", 0.05, 0.85),
            "opening_rotation_degrees": _number(source.get("opening_rotation_degrees", 0), f"Layer {index} opening rotation", -180, 180),
            "flow_amount": _number(source.get("flow_amount", 0), f"Layer {index} flowing form", 0, 1),
            "petal_fullness": _number(source.get("petal_fullness", 1), f"Layer {index} petal fullness", 0.35, 1.8),
            "tip_sharpness": _number(source.get("tip_sharpness", 1.25), f"Layer {index} tip sharpness", 0.35, 3),
            "curl_degrees": _number(source.get("curl_degrees", 18), f"Layer {index} petal curl", -90, 90),
            "band_overlap": _number(source.get("band_overlap", 0.18), f"Layer {index} band overlap", 0, 0.65),
            "mirror_wedges": _boolean(source.get("mirror_wedges"), f"Layer {index} mirrored wedge pairs", True),
        })
    if custom_svg_characters > 120_000:
        raise ValueError("Custom SVG motifs contain too much data; simplify the motifs or use fewer custom layers")
    return {
        "project_name": name,
        "diameter_mm": diameter,
        "workbed_width_mm": workbed_width,
        "workbed_height_mm": workbed_height,
        "layers": cleaned_layers,
        "processing_palette_id": str(raw.get("processing_palette_id") or "")[:80],
        "processing_palette_name": str(raw.get("processing_palette_name") or "Processing Palette")[:160],
        "material": str(raw.get("material") or "")[:160],
        "cut_entry_ref": str(raw.get("cut_entry_ref") or "")[:120],
        "cut_setting": deepcopy(raw.get("cut_setting") or {}),
    }


def _star(points=5, inner=0.22, outer=0.5):
    values = []
    for index in range(points * 2):
        angle = math.pi * index / points
        radius = outer if index % 2 == 0 else inner
        values.append((math.cos(angle) * radius, math.sin(angle) * radius))
    return Polygon(values)


def builtin_motif(name):
    """Return a centered unit motif whose recognizable axis points right."""
    if name == "circle":
        return Point(0, 0).buffer(0.5, resolution=24)
    if name == "diamond":
        return Polygon(((-0.5, 0), (0, -0.34), (0.5, 0), (0, 0.34)))
    if name == "triangle":
        return Polygon(((-0.45, -0.38), (-0.45, 0.38), (0.5, 0)))
    if name == "star":
        return _star()
    if name == "leaf":
        return Point(-0.2, 0).buffer(0.48, resolution=24).intersection(
            Point(0.2, 0).buffer(0.48, resolution=24)
        )
    if name == "heart":
        points = []
        for index in range(96):
            angle = 2 * math.pi * index / 96
            x = 16 * math.sin(angle) ** 3
            y = 13 * math.cos(angle) - 5 * math.cos(2 * angle) - 2 * math.cos(3 * angle) - math.cos(4 * angle)
            points.append((y / 34, -x / 34))
        return Polygon(points).buffer(0)
    if name == "petal":
        leaf = Point(-0.22, 0).buffer(0.5, resolution=24).intersection(
            Point(0.22, 0).buffer(0.5, resolution=24)
        )
        return affinity.scale(leaf, xfact=1.15, yfact=0.65, origin=(0, 0))
    raise ValueError(f"Unsupported mandala motif: {name}")


def _motif_geometry(layer):
    if layer["motif"] == "custom":
        return svg_to_unit_geometry(layer["custom_svg"], padding=0.04)
    return builtin_motif(layer["motif"])


def _radial_bar(radius, width, angle):
    bar = Polygon(((0, -width / 2), (radius, -width / 2), (radius, width / 2), (0, width / 2)))
    return affinity.rotate(bar, angle, origin=(0, 0), use_radians=False)


def _polar_point(radius, angle):
    return (math.cos(angle) * radius, math.sin(angle) * radius)


def _flowing_petal(inner_radius, outer_radius, center_angle, sector_angle, layer,
                   handedness=1, width_scale=1):
    """Create one curved, billowing ornamental lobe inside a radial wedge."""
    style = layer["ornament_style"]
    motif = layer["motif"]
    flow = layer["flow_amount"]
    fullness = layer["petal_fullness"] * layer["tangent_stretch"] * width_scale
    sharpness = layer["tip_sharpness"]
    curl = math.radians(layer["curl_degrees"]) * flow * handedness
    samples = 48
    left, right = [], []
    for index in range(samples + 1):
        fraction = index / samples
        smooth = fraction * fraction * (3 - 2 * fraction)
        radius = inner_radius + (outer_radius - inner_radius) * fraction
        envelope = max(0, math.sin(math.pi * fraction)) ** sharpness
        billow = 1.0
        center_shift = curl * math.sin(math.pi * fraction)
        if style == "billow":
            billow = 1 + 0.28 * math.sin(2 * math.pi * fraction) ** 2
            center_shift *= 0.72
        elif style == "paisley":
            billow = 0.82 + 0.42 * fraction
            center_shift *= 1.45
        elif style == "rose_lace":
            billow = 0.82 + 0.26 * math.sin(3 * math.pi * fraction) ** 2
            center_shift += handedness * sector_angle * 0.045 * math.sin(2 * math.pi * fraction)
        elif style == "leaf_lace":
            billow = 0.72 + 0.2 * math.sin(math.pi * fraction)
            center_shift *= 0.82
        if motif == "circle":
            billow *= 1.18 - 0.18 * math.cos(2 * math.pi * fraction)
        elif motif == "diamond":
            billow *= 0.78 + 0.44 * abs(2 * fraction - 1)
        elif motif == "triangle":
            billow *= 0.62 + 0.62 * fraction
        elif motif == "star":
            billow *= 1 + 0.18 * math.sin(4 * math.pi * fraction) ** 2
        elif motif == "heart":
            billow *= 1 + 0.24 * math.sin(2 * math.pi * fraction)
        elif motif == "leaf":
            billow *= 0.78 + 0.3 * math.sin(math.pi * fraction)
        half_width = sector_angle * 0.39 * fullness * envelope * billow
        flow_angle = center_angle + center_shift + math.radians(layer["twist_degrees"]) * flow * smooth / max(1, layer["rings"])
        left.append(_polar_point(radius, flow_angle - half_width))
        right.append(_polar_point(radius, flow_angle + half_width))
    return Polygon((*left, *reversed(right))).buffer(0)


def _flowing_band_pattern(layer, inner_limit, outer_limit):
    """Build coordinated petal bands by repeating complete ornamental wedges."""
    span = (outer_limit - inner_limit) / layer["rings"]
    sector = 2 * math.pi / layer["repetitions"]
    lobes = []
    for ring in range(layer["rings"]):
        center = inner_limit + (ring + 0.5) * span
        half_span = span * (0.5 + layer["band_overlap"]) * layer["motif_scale"] / 0.72 * layer["radial_stretch"]
        band_inner = max(inner_limit, center - half_span)
        band_outer = min(outer_limit, center + half_span)
        ring_fraction = (ring + 0.5) / layer["rings"]
        phase = math.radians(layer["rotation_degrees"] + ring_fraction * layer["twist_degrees"] * 0.34)
        if layer["alternate_rotation"] and ring % 2:
            phase += sector / 2
        for repeat in range(layer["repetitions"]):
            angle = phase + repeat * sector
            if layer["mirror_wedges"]:
                offset = sector * 0.105
                lobes.append(_flowing_petal(
                    band_inner, band_outer, angle - offset, sector, layer,
                    handedness=-1, width_scale=0.67,
                ))
                lobes.append(_flowing_petal(
                    band_inner, band_outer, angle + offset, sector, layer,
                    handedness=1, width_scale=0.67,
                ))
            else:
                lobes.append(_flowing_petal(
                    band_inner, band_outer, angle, sector, layer,
                    handedness=-1 if layer["mirror_alternating"] and repeat % 2 else 1,
                ))
    return unary_union(lobes).buffer(0) if lobes else GeometryCollection()


def _support_bridge(start_radius, end_radius, width, start_angle, sweep_degrees,
                    wave_amount, wave_amplitude, wave_position):
    """Create a straight, diagonal, or sinusoidal structural bridge.

    The baseline is the chord between an inner and outer polar anchor. The
    wave is applied normal to that chord, with its middle zero crossing moved
    by ``wave_position``. Both anchors stay fixed so the bridge continues to
    overlap the hub and rim even at the strongest supported wave setting.
    """
    start_angle_radians = math.radians(start_angle)
    end_angle_radians = math.radians(start_angle + sweep_degrees)
    start = (
        math.cos(start_angle_radians) * start_radius,
        math.sin(start_angle_radians) * start_radius,
    )
    end = (
        math.cos(end_angle_radians) * end_radius,
        math.sin(end_angle_radians) * end_radius,
    )
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length <= 1e-9:
        return Point(start).buffer(width / 2)
    normal = (-dy / length, dx / length)
    points = []
    position = min(0.9, max(0.1, wave_position))
    for index in range(65):
        fraction = index / 64
        if fraction <= position:
            wave_fraction = 0.5 * fraction / position
        else:
            wave_fraction = 0.5 + 0.5 * (fraction - position) / (1 - position)
        displacement = wave_amount * wave_amplitude * math.sin(2 * math.pi * wave_fraction)
        x = start[0] + dx * fraction + normal[0] * displacement
        y = start[1] + dy * fraction + normal[1] * displacement
        distance = math.hypot(x, y)
        maximum_radius = max(start_radius, end_radius - width / 2)
        if distance > maximum_radius:
            scale = maximum_radius / distance
            x, y = x * scale, y * scale
        points.append((x, y))
    return LineString(points).buffer(width / 2, cap_style=1, join_style=1)


def _petal_crown(radius, rim_width, repetitions, rotation_degrees=0):
    """Return repeated outer petals and the radius where support arms meet them."""
    petal = builtin_motif("petal")
    radial_size = max(rim_width * 3, radius * 0.1)
    tangent_room = 2 * math.pi * radius / repetitions
    tangent_size = min(radial_size * 0.72, tangent_room * 0.68)
    anchor_radius = radius - radial_size * 0.58
    petals = []
    for index in range(repetitions):
        item = affinity.scale(petal, xfact=radial_size, yfact=tangent_size, origin=(0, 0))
        item = affinity.translate(item, xoff=anchor_radius)
        petals.append(affinity.rotate(
            item,
            rotation_degrees + index * 360 / repetitions,
            origin=(0, 0),
        ))
    return unary_union(petals).buffer(0), anchor_radius


def _radial_circle(radius, repetitions, steps_per_sector=8):
    """Approximate a circle with vertices aligned to the layer symmetry."""
    count = max(repetitions * steps_per_sector, repetitions)
    return Polygon(
        (
            math.cos(2 * math.pi * index / count) * radius,
            math.sin(2 * math.pi * index / count) * radius,
        )
        for index in range(count)
    )


def _openwork_windows(radius, rim_width, hub_radius, repetitions, openness,
                      inner_ratio, rotation_degrees):
    """Build repeated annular-sector windows between neighboring supports."""
    if openness <= 0:
        return GeometryCollection()
    inner_radius = max(hub_radius * 1.08, radius * inner_ratio)
    outer_radius = radius - rim_width * 1.15
    if outer_radius <= inner_radius:
        return GeometryCollection()
    sector_angle = 360 / repetitions
    half_width = sector_angle * 0.41 * openness
    windows = []
    arc_steps = 8
    for index in range(repetitions):
        center = rotation_degrees + (index + 0.5) * sector_angle
        angles = [
            math.radians(center - half_width + 2 * half_width * step / arc_steps)
            for step in range(arc_steps + 1)
        ]
        points = [
            (math.cos(angle) * outer_radius, math.sin(angle) * outer_radius)
            for angle in angles
        ]
        points.extend(
            (math.cos(angle) * inner_radius, math.sin(angle) * inner_radius)
            for angle in reversed(angles)
        )
        windows.append(Polygon(points))
    return unary_union(windows).buffer(0)


def _polygon_components(geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    if geometry.geom_type == "MultiPolygon":
        return list(geometry.geoms)
    values = []
    for child in getattr(geometry, "geoms", ()):
        values.extend(_polygon_components(child))
    return values


def _connect_pattern_to_support(pattern, support, hub_radius, width, repetitions,
                                sweep_degrees, wave_amount, wave_amplitude,
                                wave_position):
    """Join every positive-pattern component to the hub/rim without losing symmetry."""
    if pattern.is_empty or support.is_empty:
        return support
    connected = support
    for component in _polygon_components(pattern):
        if component.intersects(connected):
            continue
        point = component.representative_point()
        end_radius = math.hypot(point.x, point.y)
        end_angle = math.degrees(math.atan2(point.y, point.x))
        base_start_angle = (end_angle - sweep_degrees) % (360 / repetitions)
        bridges = [
            _support_bridge(
                hub_radius * 0.75,
                end_radius,
                width,
                base_start_angle + index * 360 / repetitions,
                sweep_degrees,
                wave_amount,
                wave_amplitude,
                wave_position,
            )
            for index in range(repetitions)
        ]
        connected = unary_union((connected, *bridges)).buffer(0)
    return connected


def generate_layer_geometry(config, layer_index):
    """Generate one centered, rotationally symmetric physical layer."""
    layer = config["layers"][layer_index]
    radius = config["diameter_mm"] / 2
    rim_width = min(layer["rim_width_mm"], radius * 0.3)
    inner_limit = max(radius * layer["inner_radius_ratio"], layer["bridge_width_mm"] * 1.5)
    outer_limit = radius - rim_width * 1.2
    if outer_limit <= inner_limit:
        raise ValueError(f"{layer['name']} does not leave enough room between its center and rim")
    ring_step = (outer_limit - inner_limit) / layer["rings"]
    bridge_cap = max(0.4, ring_step * 0.24)
    bridge_width = min(layer["bridge_width_mm"], bridge_cap)
    wave_amplitude = min(layer["bridge_wave_amplitude_mm"], ring_step * 1.5)
    if layer["motif"] == "custom" or layer["flow_amount"] <= 0:
        motif = _motif_geometry(layer)
        placed = []
        for ring in range(layer["rings"]):
            fraction = (ring + 0.5) / layer["rings"]
            ring_radius = inner_limit + fraction * (outer_limit - inner_limit)
            radial_size = ring_step * layer["motif_scale"] * layer["radial_stretch"]
            tangent_room = 2 * math.pi * ring_radius / layer["repetitions"]
            tangent_size = min(ring_step * layer["motif_scale"], tangent_room * 0.72) * layer["tangent_stretch"]
            ring_phase = layer["rotation_degrees"] + fraction * layer["twist_degrees"]
            if layer["alternate_rotation"] and ring % 2:
                ring_phase += 180 / layer["repetitions"]
            for repeat in range(layer["repetitions"]):
                item = affinity.scale(
                    motif,
                    xfact=radial_size,
                    yfact=tangent_size * (-1 if layer["mirror_alternating"] and repeat % 2 else 1),
                    origin=(0, 0),
                )
                item = affinity.translate(item, xoff=ring_radius)
                placed.append(affinity.rotate(
                    item, ring_phase + repeat * 360 / layer["repetitions"],
                    origin=(0, 0), use_radians=False,
                ))
        pattern = unary_union(placed).buffer(0) if placed else GeometryCollection()
    else:
        pattern = _flowing_band_pattern(layer, inner_limit, outer_limit)
    disc = _radial_circle(radius, layer["repetitions"], 12)
    clip = _radial_circle(radius - rim_width, layer["repetitions"], 12).difference(
        _radial_circle(max(0, inner_limit * 0.42), layer["repetitions"], 8)
    )
    pattern = pattern.intersection(clip).buffer(0)
    if layer["rim_style"] == "closed":
        rim = disc.difference(_radial_circle(radius - rim_width, layer["repetitions"], 12))
        outer_anchor_radius = radius - rim_width / 2
    elif layer["rim_style"] == "petal":
        rim, outer_anchor_radius = _petal_crown(
            radius,
            rim_width,
            layer["repetitions"],
            layer["support_sweep_degrees"],
        )
        rim = rim.intersection(disc).buffer(0)
    else:
        rim = GeometryCollection()
        outer_anchor_radius = radius - bridge_width / 2
    hub_radius = max(rim_width, inner_limit * 0.42)
    hub = _radial_circle(hub_radius, layer["repetitions"], 8)
    support = GeometryCollection()
    if layer["support_mode"] != "loose":
        support = unary_union((rim, hub))
    if layer["support_mode"] in {"automatic_bridges", "fully_connected"}:
        # Supports repeat with the motif so structural reinforcement cannot
        # quietly reduce the layer's promised rotational symmetry.
        spoke_count = layer["repetitions"]
        width = bridge_width * (1.35 if layer["support_mode"] == "fully_connected" else 1)
        spokes = [
            _support_bridge(
                hub_radius * 0.75,
                outer_anchor_radius,
                width,
                index * 360 / spoke_count,
                layer["support_sweep_degrees"],
                layer["bridge_wave_amount"],
                wave_amplitude,
                layer["bridge_wave_position"],
            )
            for index in range(spoke_count)
        ]
        support = unary_union((support, *spokes))
    if layer["support_mode"] == "fully_connected":
        middle = _radial_circle(
            (inner_limit + outer_limit) / 2 + bridge_width / 2,
            layer["repetitions"], 10,
        ).difference(
            _radial_circle(
                (inner_limit + outer_limit) / 2 - bridge_width / 2,
                layer["repetitions"], 10,
            )
        )
        support = unary_union((support, middle))
    if layer["construction"] == "positive" and layer["support_mode"] in {"automatic_bridges", "fully_connected"}:
        support = _connect_pattern_to_support(
            pattern,
            support,
            hub_radius,
            bridge_width,
            layer["repetitions"],
            layer["support_sweep_degrees"],
            layer["bridge_wave_amount"],
            wave_amplitude,
            layer["bridge_wave_position"],
        )
    if layer["construction"] == "cutout":
        geometry = disc.difference(pattern)
        if not support.is_empty:
            geometry = unary_union((geometry, support))
    else:
        geometry = pattern if support.is_empty else unary_union((pattern, support))
    windows = _openwork_windows(
        radius,
        rim_width,
        hub_radius,
        layer["repetitions"],
        layer["layer_openness"],
        layer["opening_inner_ratio"],
        layer["opening_rotation_degrees"],
    )
    if not windows.is_empty:
        geometry = geometry.difference(windows)
        if not support.is_empty:
            geometry = unary_union((geometry, support))
    geometry = geometry.intersection(disc).buffer(0)
    if geometry.is_empty:
        raise ValueError(f"{layer['name']} generated no usable geometry")
    components = _polygon_components(geometry)
    if layer["construction"] == "cutout" and layer["support_mode"] in {"automatic_bridges", "fully_connected"} and len(components) > 1:
        # Subtracting overlapping ornamental bands can leave tiny trapped
        # material islands. They are not part of a usable one-piece layer, so
        # connected construction intentionally retains the structural body.
        geometry = max(components, key=lambda component: component.area).buffer(0)
        components = [geometry]
    if layer["support_mode"] in {"automatic_bridges", "fully_connected"} and len(components) != 1:
        raise ValueError(
            f"{layer['name']} could not be made into one connected piece; "
            "increase Bridge Width, reduce motif spacing, or soften the bridge wave or sweep"
        )
    coverage = geometry.area / disc.area
    if coverage < 0.01:
        raise ValueError(
            f"{layer['name']} leaves too little material to read as a mandala; "
            "increase Motif Scale or choose a connected support mode"
        )
    if coverage > 0.985:
        raise ValueError(
            f"{layer['name']} is almost completely solid; reduce Motif Scale, "
            "Bridge Width, or structural support"
        )
    return geometry


def generate_mandala(config):
    clean = validate_mandala_config(config)
    return clean, [generate_layer_geometry(clean, index) for index in range(len(clean["layers"]))]


def _polygons(geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    if geometry.geom_type == "MultiPolygon":
        return list(geometry.geoms)
    values = []
    for child in getattr(geometry, "geoms", ()):
        values.extend(_polygons(child))
    return values


def _ring_coordinates(ring, x_offset, y_offset):
    values = [(float(x) + x_offset, float(y) + y_offset) for x, y in ring.coords]
    return values[:-1] if len(values) > 1 and values[0] == values[-1] else values


def _svg_path_data(geometry, x_offset, y_offset):
    segments = []
    for polygon in _polygons(geometry):
        for ring in (polygon.exterior, *polygon.interiors):
            points = _ring_coordinates(ring, x_offset, y_offset)
            if len(points) < 3:
                continue
            segments.append("M " + " L ".join(f"{x:.5f} {y:.5f}" for x, y in points) + " Z")
    return " ".join(segments)


def write_svg(path, geometry, diameter, *, color="#111111", title="Mandala layer"):
    root = ET.Element("svg", {
        "xmlns": "http://www.w3.org/2000/svg", "version": "1.1",
        "width": f"{diameter:g}mm", "height": f"{diameter:g}mm",
        "viewBox": f"0 0 {diameter:g} {diameter:g}",
    })
    ET.SubElement(root, "title").text = title
    ET.SubElement(root, "path", {
        "d": _svg_path_data(geometry, diameter / 2, diameter / 2),
        "fill": color, "fill-rule": "evenodd", "stroke": "none",
    })
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def write_assembly_svg(path, config, geometries):
    diameter = config["diameter_mm"]
    root = ET.Element("svg", {
        "xmlns": "http://www.w3.org/2000/svg", "version": "1.1",
        "width": f"{diameter:g}mm", "height": f"{diameter:g}mm",
        "viewBox": f"0 0 {diameter:g} {diameter:g}",
    })
    ET.SubElement(root, "title").text = f"{config['project_name']} stacked assembly preview"
    for index, geometry in enumerate(geometries):
        ET.SubElement(root, "path", {
            "id": f"layer-{index + 1:02d}",
            "d": _svg_path_data(geometry, diameter / 2, diameter / 2),
            "fill": LAYER_COLORS[index % len(LAYER_COLORS)], "fill-rule": "evenodd",
            "fill-opacity": "0.42", "stroke": LAYER_COLORS[index % len(LAYER_COLORS)],
            "stroke-width": ".2",
        })
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


class _PortableCutLayer:
    """Write only values genuinely present in the selected Processing setting."""

    def __init__(self, setting, index, name):
        self.setting = setting if isinstance(setting, dict) else {}
        self.index = index
        self.name = name

    def write(self, stream):
        root = ET.Element("CutSetting", {"type": "Cut"})
        ET.SubElement(root, "index", {"Value": str(self.index)})
        ET.SubElement(root, "name", {"Value": self.name})
        values = self.setting.get("settings")
        values = values if isinstance(values, dict) else {}
        for field, value in values.items():
            if field in {"index", "name", "LinkPath", "linkPath"} or value in (None, ""):
                continue
            if isinstance(value, (dict, list)):
                continue
            ET.SubElement(root, str(field), {"Value": str(value)})
        stream.write("    " + ET.tostring(root, encoding="unicode") + "\n")


def _add_geometry(project, geometry, layer_index, center_x, center_y):
    count = 0
    for polygon in _polygons(geometry):
        rings = (polygon.exterior, *polygon.interiors)
        for ring in rings:
            points = _ring_coordinates(ring, center_x, center_y)
            if len(points) >= 3:
                project.add(lightburn.Path(points, closed=True).layer(layer_index))
                count += 1
    return count


def write_lightburn(path, config, geometries, layer_indexes=None):
    selected = list(range(len(geometries))) if layer_indexes is None else list(layer_indexes)
    project = lightburn.Lightburn()
    setting = config.get("cut_setting") or {}
    center_x = config["workbed_width_mm"] / 2
    center_y = config["workbed_height_mm"] / 2
    path_count = 0
    for output_index, source_index in enumerate(selected):
        name = f"{source_index + 1:02d} {config['layers'][source_index]['name']}"
        project.add_layer(_PortableCutLayer(setting, output_index, name))
        path_count += _add_geometry(project, geometries[source_index], output_index, center_x, center_y)
    project.set_notes(
        f"Layered Mandala Lab\nProject: {config['project_name']}\n"
        f"Finished diameter: {config['diameter_mm']:g} mm\n"
        f"Layer order: front to back\nPhysical layers: {len(selected)}\n"
        "Inspect every path and assign safe machine settings before cutting.",
        show_on_load=True,
    )
    project.write(path)
    return path_count


def build_mandala_exports(output_directory, config):
    """Generate combined and per-layer artifacts; return paths and summary."""
    clean, geometries = generate_mandala(config)
    directory = Path(output_directory)
    directory.mkdir(parents=True, exist_ok=True)
    stem = "".join(character.lower() if character.isalnum() else "-" for character in clean["project_name"]).strip("-") or "layered-mandala"
    stem = "-".join(part for part in stem.split("-") if part)[:80]
    combined = directory / f"{stem}-combined.lbrn2"
    assembly = directory / f"{stem}-assembly.svg"
    path_count = write_lightburn(combined, clean, geometries)
    write_assembly_svg(assembly, clean, geometries)
    manifest = {
        "schema_version": 1,
        "project_name": clean["project_name"],
        "diameter_mm": clean["diameter_mm"],
        "workbed_mm": [clean["workbed_width_mm"], clean["workbed_height_mm"]],
        "layer_order": "front_to_back",
        "processing_palette": clean["processing_palette_name"],
        "material": clean["material"],
        "cut_setting": str((clean.get("cut_setting") or {}).get("description") or "Cut"),
        "layers": [],
    }
    archive = directory / f"{stem}-layers.zip"
    staging = directory / f"{stem}-layers"
    staging.mkdir(exist_ok=True)
    for index, (layer, geometry) in enumerate(zip(clean["layers"], geometries), start=1):
        layer_stem = f"{index:02d}-{''.join(c.lower() if c.isalnum() else '-' for c in layer['name']).strip('-') or 'layer'}"
        svg_path = staging / f"{layer_stem}.svg"
        lightburn_path = staging / f"{layer_stem}.lbrn2"
        write_svg(svg_path, geometry, clean["diameter_mm"], color=LAYER_COLORS[(index - 1) % len(LAYER_COLORS)], title=layer["name"])
        layer_paths = write_lightburn(lightburn_path, clean, geometries, [index - 1])
        manifest["layers"].append({
            "index": index, "name": layer["name"], "motif": layer["motif"],
            "construction": layer["construction"], "support_mode": layer["support_mode"],
            "path_count": layer_paths, "area_mm2": round(float(geometry.area), 5),
            "svg": svg_path.name, "lightburn": lightburn_path.name,
        })
    manifest_path = staging / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    assembly_copy = staging / assembly.name
    assembly_copy.write_bytes(assembly.read_bytes())
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for item in sorted(staging.iterdir()):
            bundle.write(item, item.name)
    return {
        "outputs": [str(combined), str(assembly), str(archive)],
        "layer_count": len(geometries),
        "path_count": path_count,
        "manifest": manifest,
    }

"""Curated rolling-gear artwork generation for SpiralGrap Lab."""

from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree as ET

from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, box

from lib import lightburn
from lib.custom_shape import svg_to_unit_geometry


TRACK_TEETH = {"circle": 96, "oval": 105, "rounded_square": 120, "rounded_triangle": 105, "custom": 120}
GEAR_TEETH = (24, 30, 32, 36, 40, 42, 45, 48, 56, 60)
PEN_HOLES = {1: .2, 2: .36, 3: .52, 4: .68, 5: .82, 6: .94}
TRACKS = set(TRACK_TEETH)
SIDES = {"inside", "outside"}
DIRECTIONS = {"clockwise", "counterclockwise"}
OUTPUT_MODES = {"line", "fill"}
COLORS = ("#e44d61", "#f39c49", "#e4d354", "#72c66a", "#43b7a7", "#4c9dde")


def _number(value, name, minimum, maximum):
    try:
        value = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be a number") from error
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum:g} and {maximum:g}")
    return value


def _integer(value, name, allowed):
    try:
        value = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Choose a valid {name}") from error
    if value not in allowed:
        raise ValueError(f"Choose a valid {name}")
    return value


def validate_spiralgrap_config(raw):
    if not isinstance(raw, dict):
        raise ValueError("SpiralGrap settings could not be read")
    name = str(raw.get("project_name") or "SpiralGrap Project").strip()[:120]
    diameter = _number(raw.get("diameter_mm", 150), "Finished diameter", 20, 1000)
    width = _number(raw.get("workbed_width_mm", diameter), "Workbed width", diameter, 3000)
    height = _number(raw.get("workbed_height_mm", diameter), "Workbed height", diameter, 3000)
    layers = raw.get("layers")
    if not isinstance(layers, list) or not 1 <= len(layers) <= 6:
        raise ValueError("A SpiralGrap project needs 1 to 6 drawing layers")
    clean_layers = []
    svg_characters = 0
    for index, source in enumerate(layers, start=1):
        if not isinstance(source, dict):
            raise ValueError(f"SpiralGrap layer {index} could not be read")
        track = str(source.get("track") or "circle").strip().lower()
        if track not in TRACKS:
            raise ValueError(f"SpiralGrap layer {index} has an unsupported track plate")
        custom_svg = source.get("custom_svg")
        if track == "custom":
            if not isinstance(custom_svg, dict) or not isinstance(custom_svg.get("svg"), str):
                raise ValueError(f"SpiralGrap layer {index} needs a closed-path SVG track")
            svg_characters += len(custom_svg["svg"])
            svg_to_unit_geometry(custom_svg, padding=.02)
            custom_svg = {"name": str(custom_svg.get("name") or "custom-track.svg")[:120], "svg": custom_svg["svg"]}
        else:
            custom_svg = None
        side = str(source.get("side") or "inside").strip().lower()
        direction = str(source.get("direction") or "clockwise").strip().lower()
        if side not in SIDES or direction not in DIRECTIONS:
            raise ValueError(f"SpiralGrap layer {index} has an invalid rolling choice")
        output_mode = str(source.get("output_mode") or "line").strip().lower()
        if output_mode not in OUTPUT_MODES:
            raise ValueError(f"SpiralGrap layer {index} has an invalid output mode")
        clean_layers.append({
            "name": str(source.get("name") or f"Drawing {index}").strip()[:80] or f"Drawing {index}",
            "track": track,
            "custom_svg": custom_svg,
            "gear_teeth": _integer(source.get("gear_teeth", 40), "rolling gear", GEAR_TEETH),
            "pen_hole": _integer(source.get("pen_hole", 5), "pen hole", PEN_HOLES),
            "side": side,
            "start_mark": _integer(source.get("start_mark", 1), "starting mark", range(1, 9)),
            "direction": direction,
            "rotation_quarter_turns": _integer(source.get("rotation_quarter_turns", 0), "track rotation", range(4)),
            "include_track": bool(source.get("include_track", False)),
            "output_mode": output_mode,
            "fill_thickness_mm": _number(source.get("fill_thickness_mm", 1.2), "Fill thickness", .1, 25),
        })
    if svg_characters > 120_000:
        raise ValueError("Custom SpiralGrap SVG tracks contain too much data")
    return {
        "project_name": name or "SpiralGrap Project",
        "diameter_mm": diameter,
        "workbed_width_mm": width,
        "workbed_height_mm": height,
        "layers": clean_layers,
        "processing_palette_id": str(raw.get("processing_palette_id") or "")[:80],
        "processing_palette_name": str(raw.get("processing_palette_name") or "Processing Palette")[:160],
        "material": str(raw.get("material") or "")[:160],
        "score_entry_ref": str(raw.get("score_entry_ref") or "")[:120],
        "score_setting": deepcopy(raw.get("score_setting") or {}),
        "fill_entry_ref": str(raw.get("fill_entry_ref") or "")[:120],
        "fill_setting": deepcopy(raw.get("fill_setting") or {}),
    }


def _largest_polygon(geometry):
    if geometry.geom_type == "Polygon":
        return geometry
    polygons = [item for item in getattr(geometry, "geoms", ()) if item.geom_type == "Polygon"]
    if not polygons:
        raise ValueError("The custom track SVG does not contain a usable closed path")
    return max(polygons, key=lambda item: item.area)


def _track_line(layer):
    track = layer["track"]
    if track == "circle":
        polygon = Point(0, 0).buffer(.5, resolution=128)
    elif track == "oval":
        polygon = affinity.scale(Point(0, 0).buffer(.5, resolution=128), xfact=1, yfact=.68)
    elif track == "rounded_square":
        polygon = box(-.39, -.39, .39, .39).buffer(.11, resolution=24)
    elif track == "rounded_triangle":
        triangle = Polygon(((0, -.5), (.433, .25), (-.433, .25)))
        polygon = triangle.buffer(-.07, join_style=1).buffer(.07, resolution=24, join_style=1)
    else:
        polygon = _largest_polygon(svg_to_unit_geometry(layer["custom_svg"], padding=.02))
    polygon = affinity.rotate(polygon, layer["rotation_quarter_turns"] * 90, origin=(0, 0))
    return LineString(polygon.exterior.coords)


def _sample_closed(line, distance):
    length = line.length
    point = line.interpolate(distance % length)
    delta = max(length / 20000, 1e-7)
    before = line.interpolate((distance - delta) % length)
    after = line.interpolate((distance + delta) % length)
    dx, dy = after.x - before.x, after.y - before.y
    magnitude = math.hypot(dx, dy) or 1
    return point.x, point.y, dx / magnitude, dy / magnitude


def generate_layer(layer, diameter):
    track = _track_line(layer)
    perimeter = track.length
    track_teeth = TRACK_TEETH[layer["track"]]
    gear_teeth = layer["gear_teeth"]
    gear_radius = perimeter / (2 * math.pi) * gear_teeth / track_teeth
    pen_radius = gear_radius * PEN_HOLES[layer["pen_hole"]]
    loops = gear_teeth // math.gcd(track_teeth, gear_teeth)
    samples = min(24000, max(1200, loops * track_teeth * 10))
    phase = (layer["start_mark"] - 1) * math.pi / 4
    roll_sign = -1 if layer["direction"] == "clockwise" else 1
    side_sign = -1 if layer["side"] == "inside" else 1
    points = []
    for index in range(samples + 1):
        distance = perimeter * loops * index / samples
        x, y, tx, ty = _sample_closed(track, distance)
        nx, ny = ty, -tx
        center_x, center_y = x + nx * gear_radius * side_sign, y + ny * gear_radius * side_sign
        pen_angle = phase + roll_sign * side_sign * distance / gear_radius
        points.append((center_x + math.cos(pen_angle) * pen_radius, center_y + math.sin(pen_angle) * pen_radius))
    points[-1] = points[0]
    curve = LineString(points)
    all_bounds = curve.bounds
    if layer["include_track"]:
        track_bounds = track.bounds
        all_bounds = (
            min(all_bounds[0], track_bounds[0]), min(all_bounds[1], track_bounds[1]),
            max(all_bounds[2], track_bounds[2]), max(all_bounds[3], track_bounds[3]),
        )
    extent = max(all_bounds[2] - all_bounds[0], all_bounds[3] - all_bounds[1]) or 1
    scale = diameter / extent * .94
    center_x = (all_bounds[0] + all_bounds[2]) / 2
    center_y = (all_bounds[1] + all_bounds[3]) / 2
    curve = affinity.translate(curve, xoff=-center_x, yoff=-center_y)
    curve = affinity.scale(curve, xfact=scale, yfact=scale, origin=(0, 0))
    outline = None
    if layer["include_track"]:
        outline = affinity.translate(track, xoff=-center_x, yoff=-center_y)
        outline = affinity.scale(outline, xfact=scale, yfact=scale, origin=(0, 0))
    return curve.simplify(max(.002, diameter / 100000), preserve_topology=False), outline


def generate_spiralgrap(config):
    clean = validate_spiralgrap_config(config)
    return clean, [generate_layer(layer, clean["diameter_mm"]) for layer in clean["layers"]]


def _coords(line, xoff=0, yoff=0):
    values = [(float(x) + xoff, float(y) + yoff) for x, y in line.coords]
    return values[:-1] if len(values) > 1 and values[0] == values[-1] else values


def _fill_polygons(curve, thickness):
    geometry = curve.buffer(thickness / 2, cap_style=1, join_style=1)
    return [geometry] if geometry.geom_type == "Polygon" else [item for item in getattr(geometry, "geoms", ()) if item.geom_type == "Polygon"]


def _fill_rings(curve, thickness):
    rings = []
    for polygon in _fill_polygons(curve, thickness):
        if polygon.is_empty:
            continue
        rings.append(LineString(polygon.exterior.coords))
        rings.extend(LineString(interior.coords) for interior in polygon.interiors)
    return rings


def write_svg(path, config, generated):
    diameter = config["diameter_mm"]
    root = ET.Element("svg", {"xmlns": "http://www.w3.org/2000/svg", "version": "1.1", "width": f"{diameter:g}mm", "height": f"{diameter:g}mm", "viewBox": f"0 0 {diameter:g} {diameter:g}"})
    ET.SubElement(root, "title").text = config["project_name"]
    for index, ((curve, outline), layer) in enumerate(zip(generated, config["layers"])):
        if layer["output_mode"] == "fill":
            for number, polygon in enumerate(_fill_polygons(curve, layer["fill_thickness_mm"]), start=1):
                rings = [polygon.exterior, *polygon.interiors]
                commands = []
                for ring in rings:
                    points = _coords(LineString(ring.coords), diameter / 2, diameter / 2)
                    commands.append("M " + " L ".join(f"{x:.5f} {y:.5f}" for x, y in points) + " Z")
                ET.SubElement(root, "path", {"id": f"layer-{index + 1}-curve-{number}", "d": " ".join(commands), "fill": COLORS[index % len(COLORS)], "fill-rule": "evenodd", "stroke": COLORS[index % len(COLORS)], "stroke-width": ".2"})
        else:
            points = _coords(curve, diameter / 2, diameter / 2)
            ET.SubElement(root, "path", {"id": f"layer-{index + 1}-curve-1", "d": "M " + " L ".join(f"{x:.5f} {y:.5f}" for x, y in points), "fill": "none", "stroke": COLORS[index % len(COLORS)], "stroke-width": ".2"})
        for name, line, opacity in (("track", outline, ".35"),):
            if line is None:
                continue
            points = _coords(line, diameter / 2, diameter / 2)
            ET.SubElement(root, "path", {"id": f"layer-{index + 1}-{name}", "d": "M " + " L ".join(f"{x:.5f} {y:.5f}" for x, y in points) + " Z", "fill": "none", "stroke": COLORS[index % len(COLORS)], "stroke-width": ".2", "stroke-opacity": opacity})
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


class _PortableLayer:
    def __init__(self, setting, index, name, fallback_type):
        self.setting, self.index, self.name, self.fallback_type = setting or {}, index, name, fallback_type
    def write(self, stream):
        root = ET.Element("CutSetting", {"type": str(self.setting.get("type") or self.fallback_type)})
        ET.SubElement(root, "index", {"Value": str(self.index)})
        ET.SubElement(root, "name", {"Value": self.name})
        for field, value in (self.setting.get("settings") or {}).items():
            if field not in {"index", "name", "LinkPath", "linkPath"} and value not in (None, "") and not isinstance(value, (dict, list)):
                ET.SubElement(root, str(field), {"Value": str(value)})
        stream.write("    " + ET.tostring(root, encoding="unicode") + "\n")


def write_lightburn(path, config, generated):
    project = lightburn.Lightburn()
    center_x, center_y = config["workbed_width_mm"] / 2, config["workbed_height_mm"] / 2
    lightburn_index = 0
    for index, ((curve, outline), layer) in enumerate(zip(generated, config["layers"])):
        is_fill = layer["output_mode"] == "fill"
        setting = config["fill_setting"] if is_fill else config["score_setting"]
        project.add_layer(_PortableLayer(setting, lightburn_index, f"{index + 1:02d} {layer['name']}", "Scan" if is_fill else "Cut"))
        if is_fill:
            for ring in _fill_rings(curve, layer["fill_thickness_mm"]):
                project.add(lightburn.Path(_coords(ring, center_x, center_y), closed=True).layer(lightburn_index))
        else:
            project.add(lightburn.Path(_coords(curve, center_x, center_y), closed=False).layer(lightburn_index))
        lightburn_index += 1
        if outline is not None:
            project.add_layer(_PortableLayer(config["score_setting"], lightburn_index, f"{index + 1:02d} {layer['name']} track", "Cut"))
            project.add(lightburn.Path(_coords(outline, center_x, center_y), closed=True).layer(lightburn_index))
            lightburn_index += 1
    project.set_notes(f"SpiralGrap Lab\nProject: {config['project_name']}\nDiameter: {config['diameter_mm']:g} mm\nReview every path and laser setting before execution.", show_on_load=True)
    project.write(path)


def build_spiralgrap_exports(output_directory, config):
    clean, generated = generate_spiralgrap(config)
    directory = Path(output_directory)
    directory.mkdir(parents=True, exist_ok=True)
    stem = "".join(c.lower() if c.isalnum() else "-" for c in clean["project_name"]).strip("-") or "spiralgrap"
    stem = "-".join(part for part in stem.split("-") if part)[:80]
    svg_path = directory / f"{stem}.svg"
    lightburn_path = directory / f"{stem}.lbrn2"
    manifest_path = directory / f"{stem}.json"
    write_svg(svg_path, clean, generated)
    write_lightburn(lightburn_path, clean, generated)
    manifest_path.write_text(json.dumps({"schema_version": 1, "project_name": clean["project_name"], "diameter_mm": clean["diameter_mm"], "layers": [{key: value for key, value in layer.items() if key != "custom_svg"} for layer in clean["layers"]]}, indent=2), encoding="utf-8")
    return {"outputs": [str(svg_path), str(lightburn_path), str(manifest_path)], "layer_count": len(generated), "point_count": sum(len(curve.coords) + (len(outline.coords) if outline is not None else 0) for curve, outline in generated)}

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from lib.spiralgrap import build_spiralgrap_exports, generate_spiralgrap, validate_spiralgrap_config


def layer(**overrides):
    value = {
        "name": "Classic curve", "track": "circle", "gear_teeth": 40,
        "pen_hole": 5, "side": "inside", "start_mark": 1,
        "direction": "clockwise", "rotation_quarter_turns": 0,
        "include_track": False, "output_mode": "line", "fill_thickness_mm": 1.2,
    }
    value.update(overrides)
    return value


def config(*layers):
    return {
        "project_name": "SpiralGraph Test", "diameter_mm": 120,
        "workbed_width_mm": 180, "workbed_height_mm": 160,
        "score_setting": {"type": "Cut", "settings": {"speed": 100}},
        "fill_setting": {"type": "Scan", "settings": {"speed": 200}},
        "layers": list(layers or (layer(),)),
    }


def test_curated_curve_closes_and_scales_to_requested_size():
    clean, generated = generate_spiralgrap(config(layer(track="oval", gear_teeth=42)))
    curve, _ = generated[0]
    assert clean["layers"][0]["gear_teeth"] == 42
    assert curve.coords[0] == curve.coords[-1]
    bounds = curve.bounds
    assert max(bounds[2] - bounds[0], bounds[3] - bounds[1]) == pytest.approx(112.8, abs=.2)


def test_component_sizes_are_preserved_and_drawing_size_controls_final_footprint():
    customized = layer(
        track="oval",
        track_width_percent=140,
        track_height_percent=65,
        gear_size_percent=125,
        pen_reach_percent=75,
        drawing_size_percent=60,
    )
    clean, generated = generate_spiralgrap(config(customized))
    curve, _ = generated[0]
    saved = clean["layers"][0]
    assert saved["track_width_percent"] == 140
    assert saved["track_height_percent"] == 65
    assert saved["gear_size_percent"] == 125
    assert saved["pen_reach_percent"] == 75
    assert saved["drawing_size_percent"] == 60
    assert curve.coords[0] == curve.coords[-1]
    bounds = curve.bounds
    assert max(bounds[2] - bounds[0], bounds[3] - bounds[1]) == pytest.approx(67.68, abs=.2)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("track_width_percent", 39, "Track width percent"),
        ("track_height_percent", 161, "Track height percent"),
        ("gear_size_percent", 49, "Gear size percent"),
        ("pen_reach_percent", 126, "Pen reach percent"),
        ("drawing_size_percent", 19, "Drawing size percent"),
    ),
)
def test_component_size_ranges_are_validated(field, value, message):
    with pytest.raises(ValueError, match=message):
        validate_spiralgrap_config(config(layer(**{field: value})))


def test_custom_track_requires_a_closed_svg_path():
    open_svg = '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0 L10 0 L10 10"/></svg>'
    with pytest.raises(ValueError, match="closed shape"):
        validate_spiralgrap_config(config(layer(track="custom", custom_svg={"name": "open.svg", "svg": open_svg})))
    closed_svg = '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0 L10 0 L8 10 L0 8 Z"/></svg>'
    clean, generated = generate_spiralgrap(config(layer(track="custom", custom_svg={"name": "closed.svg", "svg": closed_svg})))
    assert clean["layers"][0]["custom_svg"]["name"] == "closed.svg"
    assert not generated[0][0].is_empty


def test_exports_preserve_open_lines_and_closed_fill_ribbons(tmp_path):
    result = build_spiralgrap_exports(tmp_path, config(
        layer(name="Open line", output_mode="line"),
        layer(name="Ribbon", track="rounded_square", output_mode="fill", fill_thickness_mm=2, include_track=True),
    ))
    lightburn_path = next(Path(path) for path in result["outputs"] if path.endswith(".lbrn2"))
    svg_path = next(Path(path) for path in result["outputs"] if path.endswith(".svg"))
    text = lightburn_path.read_text(encoding="utf-8")
    assert 'type="Cut"' in text and 'type="Scan"' in text
    assert "Open line" in text and "Ribbon" in text and "Ribbon track" in text
    first_primitive = text.split("<PrimList>", 1)[1].split("</PrimList>", 1)[0]
    assert "LineClosed" not in first_primitive
    assert "<PrimList>LineClosed</PrimList>" in text
    svg = ET.parse(svg_path).getroot()
    paths = svg.findall("{http://www.w3.org/2000/svg}path")
    assert any(item.get("fill") == "none" and not item.get("d", "").endswith(" Z") for item in paths)
    assert any(item.get("fill") != "none" and item.get("d", "").endswith(" Z") for item in paths)


def test_optional_swatch_controls_svg_lightburn_color_and_per_swatch_setting(tmp_path):
    blue_fill = {"description": "Blue Fill", "type": "Scan", "settings": {"speed": 250, "interval": 0.08}}
    red_cut = {"description": "Red Cut", "type": "Cut", "settings": {"speed": 80}}
    result = build_spiralgrap_exports(tmp_path, config(
        layer(name="Blue curve", swatch_hex="#0000FF", lightburn_index=1, include_track=True,
              output_mode="fill", laser_setting=blue_fill),
        layer(name="Blue curve again", track="oval", swatch_hex="#0000FF", lightburn_index=1,
              output_mode="fill", laser_setting=blue_fill),
        layer(name="Red curve", track="rounded_triangle", swatch_hex="#FF0000", lightburn_index=2,
              output_mode="line", laser_setting=red_cut),
    ))
    svg_path = next(Path(path) for path in result["outputs"] if path.endswith(".svg"))
    lightburn_path = next(Path(path) for path in result["outputs"] if path.endswith(".lbrn2"))
    svg_text = svg_path.read_text(encoding="utf-8")
    lightburn_text = lightburn_path.read_text(encoding="utf-8")
    assert 'stroke="#0000FF"' in svg_text
    assert 'stroke="#FF0000"' in svg_text
    assert '<index Value="1"' in lightburn_text
    assert '<index Value="2"' in lightburn_text
    assert lightburn_text.count('<index Value="1"') == 1
    assert '<speed Value="250"' in lightburn_text
    assert '<speed Value="80"' in lightburn_text
    assert lightburn_text.count('CutIndex="1"') > 2
    assert '<PrimList>LineClosed</PrimList>' in lightburn_text


def test_builtin_swatch_controls_svg_without_changing_processing_palette_settings(tmp_path):
    result = build_spiralgrap_exports(tmp_path, config(
        layer(name="Built-in cyan", swatch_hex="#43C7BB", output_mode="line"),
    ))
    svg_path = next(Path(path) for path in result["outputs"] if path.endswith(".svg"))
    lightburn_path = next(Path(path) for path in result["outputs"] if path.endswith(".lbrn2"))
    svg_text = svg_path.read_text(encoding="utf-8")
    lightburn_text = lightburn_path.read_text(encoding="utf-8")
    assert 'stroke="#43C7BB"' in svg_text
    assert '<speed Value="100"' in lightburn_text
    assert '<index Value="0"' in lightburn_text


def test_unoffered_raw_gear_sizes_are_rejected():
    with pytest.raises(ValueError, match="rolling gear"):
        validate_spiralgrap_config(config(layer(gear_teeth=37)))

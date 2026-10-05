import math
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from custom_shape import (  # noqa: E402
    MAX_SVG_POINTS,
    _geometry_point_count,
    svg_to_unit_geometry,
)
from abstract_filters import krasnow_grating  # noqa: E402


def test_over_detailed_custom_svg_is_automatically_simplified_for_reuse():
    segment_count = 420
    radius = 900
    center = 1000
    angle_step = 2 * math.pi / segment_count
    commands = [f"M{center + radius:.3f},{center:.3f}"]
    for index in range(segment_count):
        end_angle = (index + 1) * angle_step
        middle_angle = (index + .5) * angle_step
        control_radius = radius / math.cos(angle_step / 2)
        commands.append(
            f"Q{center + control_radius * math.cos(middle_angle):.3f},"
            f"{center + control_radius * math.sin(middle_angle):.3f} "
            f"{center + radius * math.cos(end_angle):.3f},"
            f"{center + radius * math.sin(end_angle):.3f}"
        )
    commands.append("Z")
    assert segment_count * 12 > MAX_SVG_POINTS

    geometry = svg_to_unit_geometry({
        "name": "over-detailed-circle.svg",
        "svg": (
            '<svg viewBox="0 0 2000 2000"><path d="'
            + " ".join(commands)
            + '"/></svg>'
        ),
    }, padding=0)

    assert _geometry_point_count(geometry) <= MAX_SVG_POINTS
    assert geometry.area == pytest.approx(math.pi * .5 ** 2, rel=.002)
    assert geometry.bounds == pytest.approx((-.5, -.5, .5, .5))
    assert krasnow_grating._tessellated_cells(
        (0, 0, 1, 1), 1, "custom", custom_template=geometry,
    )


def test_automatic_svg_simplification_preserves_holes():
    outer = " ".join(
        f"{1000 + round(900 * math.cos(2 * math.pi * index / 4200))},"
        f"{1000 + round(900 * math.sin(2 * math.pi * index / 4200))}"
        for index in range(4200)
    )
    geometry = svg_to_unit_geometry({
        "name": "over-detailed-ring.svg",
        "svg": (
            '<svg viewBox="0 0 2000 2000">'
            f'<polygon points="{outer}"/>'
            '<circle cx="1000" cy="1000" r="350"/>'
            '</svg>'
        ),
    }, padding=0)

    assert _geometry_point_count(geometry) <= MAX_SVG_POINTS
    assert not geometry.contains(geometry.centroid)

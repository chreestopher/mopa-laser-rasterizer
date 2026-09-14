import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from vector_processing import create_svg_root


def test_svg_root_uses_scaled_canvas_when_requested_width_is_blank():
    root = create_svg_root(
        width=600,
        height=400,
        new_width="",
        new_height="400",
        scale_factor=0.125,
    )

    assert root.attrib["viewBox"] == "0 0 75 50"
    assert root.attrib["width"] == "75mm"
    assert root.attrib["height"] == "50mm"
    assert root.attrib["xmlns"] == "http://www.w3.org/2000/svg"


def test_svg_root_does_not_use_a_zero_requested_dimension():
    root = create_svg_root(
        width=320,
        height=180,
        new_width="0",
        new_height="180",
        scale_factor=0.2,
    )

    assert root.attrib["viewBox"] == "0 0 64 36"
    assert root.attrib["width"] == "64mm"
    assert root.attrib["height"] == "36mm"
    assert root.attrib["xmlns"] == "http://www.w3.org/2000/svg"

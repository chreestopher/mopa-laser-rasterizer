from pathlib import Path
import sys
from unittest.mock import patch

from PIL import Image
import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import vector_processing


def _capture_pipeline(tmp_path, white_is):
    image_path = tmp_path / f"white-{white_is}.png"
    image = Image.new("RGB", (3, 3), (255, 255, 255))
    image.putpixel((1, 1), (255, 0, 0))
    image.save(image_path)
    captured = {}

    with patch.object(
        vector_processing,
        "export_processed_layers",
        side_effect=lambda **kwargs: captured.update(kwargs),
    ), patch.object(vector_processing, "save_vector_output"):
        vector_processing.raster_to_puzzle_and_lightburn(
            raster_image_path=image_path,
            output_svg_path=str(tmp_path / f"white-{white_is}.svg"),
            new_height=0,
            new_width=3,
            lb_project_instance=object(),
            TARGET_COLORS={
                "#000000": (0, 0, "Black"),
                "#FF0000": (0, 2, "Red"),
            },
            scale_factor=1,
            image_preset="cartoon",
            abstract_filter="none",
            export_lightburn=False,
            job_settings={"white_is": white_is},
            white_is=white_is,
        )
    return captured


def test_source_nonwhite_mask_excludes_only_exact_opaque_white(tmp_path):
    image_path = tmp_path / "white-mask.png"
    image = Image.new("RGBA", (3, 1), (255, 255, 255, 255))
    image.putpixel((1, 0), (254, 255, 255, 255))
    image.putpixel((2, 0), (255, 0, 0, 255))
    image.save(image_path)

    mask = vector_processing.load_resized_source_nonwhite_mask(image_path, (3, 1))

    assert mask.tolist() == [[False, True, True]]


def test_unengraved_white_is_removed_from_color_and_backing_layers(tmp_path):
    captured = _capture_pipeline(tmp_path, "unengraved")
    white_pixel = vector_processing.box(0, 0, 1, 1)
    colored_pixel = vector_processing.box(1, 1, 2, 2)

    for geometry in captured["processed_layers"].values():
        assert geometry.intersection(white_pixel).area == pytest.approx(0)
        assert geometry.difference(colored_pixel).area == pytest.approx(0)

    # The complete LightBurn Black carrier is clipped too; its nested colored
    # path punches this remaining pixel through during export.
    assert captured["black_lightburn_geometry"].difference(colored_pixel).area == pytest.approx(0)


def test_engraved_white_remains_backward_compatible(tmp_path):
    captured = _capture_pipeline(tmp_path, "engraved")
    full_canvas = vector_processing.box(0, 0, 3, 3)

    exported_area = vector_processing.unary_union(
        list(captured["processed_layers"].values())
    )
    assert exported_area.symmetric_difference(full_canvas).area == pytest.approx(0, abs=1e-8)


def test_white_selector_is_wired_through_ui_api_worker_and_cli():
    web = (ROOT / "serverless_web" / "index.html").read_text(encoding="utf-8")
    api = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")
    service = (ROOT / "services.py").read_text(encoding="utf-8")
    cli = (ROOT / "lib" / "Material_Library.py").read_text(encoding="utf-8")

    assert 'for="whiteIs">White Is:' in web
    assert '<option value="engraved">Engraved with White</option>' in web
    assert '<option value="unengraved">Unengraved</option>' in web
    assert "white_is:document.querySelector('#whiteIs').value" in web
    assert 'data["white_is"] = white_is' in api
    assert 'data.get("white_is", "engraved")' in service
    assert "white_is=white_is" in cli

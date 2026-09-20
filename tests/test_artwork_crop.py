from pathlib import Path
import sys
from unittest.mock import patch

from PIL import Image
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import vector_processing


def test_crop_boundary_shapes_have_expected_bounds_and_area():
    rectangle = vector_processing.artwork_crop_geometry(12, 8, "rectangle")
    oval = vector_processing.artwork_crop_geometry(12, 8, "oval")
    circle = vector_processing.artwork_crop_geometry(12, 8, "circle")

    assert rectangle.area == pytest.approx(96)
    assert oval.bounds == pytest.approx((0, 0, 12, 8), abs=1e-6)
    assert oval.area == pytest.approx(3.14159 * 6 * 4, rel=2e-4)
    assert circle.bounds == pytest.approx((2, 0, 10, 8), abs=1e-6)
    assert circle.area == pytest.approx(3.14159 * 4 * 4, rel=2e-4)


def test_invalid_crop_shape_is_rejected():
    with pytest.raises(ValueError, match="valid artwork crop shape"):
        vector_processing.artwork_crop_geometry(10, 10, "freehand")


def test_transparency_mask_preserves_internal_holes(tmp_path):
    image_path = tmp_path / "alpha-hole.png"
    image = Image.new("RGBA", (7, 7), (255, 0, 0, 0))
    for y in range(1, 6):
        for x in range(1, 6):
            image.putpixel((x, y), (255, 0, 0, 255))
    image.putpixel((3, 3), (255, 0, 0, 0))
    image.save(image_path)

    mask = vector_processing.load_resized_artwork_alpha_mask(image_path, (7, 7))
    geometry = vector_processing._mask_to_merged_geometry(mask)

    assert mask.sum() == 24
    assert geometry.area == 24
    assert geometry.intersection(vector_processing.box(3, 3, 4, 4)).area == 0


def test_transparency_crop_clips_exterior_and_internal_holes(tmp_path):
    image_path = tmp_path / "alpha-hole.png"
    image = Image.new("RGBA", (7, 7), (255, 0, 0, 0))
    for y in range(1, 6):
        for x in range(1, 6):
            image.putpixel((x, y), (255, 0, 0, 255))
    image.putpixel((3, 3), (255, 0, 0, 0))
    image.save(image_path)
    captured = {}

    with patch.object(
        vector_processing, "export_processed_layers", side_effect=lambda **kwargs: captured.update(kwargs)
    ), patch.object(vector_processing, "save_vector_output"):
        vector_processing.raster_to_puzzle_and_lightburn(
            raster_image_path=image_path,
            output_svg_path=str(tmp_path / "transparency-cropped.svg"),
            new_height=0,
            new_width=7,
            lb_project_instance=object(),
            TARGET_COLORS={
                "#000000": (0, 0, "Black"),
                "#FF0000": (0, 2, "Red"),
            },
            scale_factor=1,
            image_preset="cartoon",
            abstract_filter="none",
            export_lightburn=False,
            crop_shape="transparency",
        )

    mask = vector_processing.load_resized_artwork_alpha_mask(image_path, (7, 7))
    boundary = vector_processing._mask_to_merged_geometry(mask)
    hole = vector_processing.box(3, 3, 4, 4)
    for geometry in captured["processed_layers"].values():
        assert geometry.difference(boundary).area <= 1e-9
        assert geometry.intersection(hole).area <= 1e-9
    assert captured["black_lightburn_geometry"].difference(boundary).area <= 1e-9
    assert captured["black_lightburn_geometry"].intersection(hole).area <= 1e-9


def test_oval_crop_clips_every_pipeline_layer_before_export(tmp_path):
    image_path = tmp_path / "solid-red.png"
    Image.new("RGB", (12, 8), (255, 0, 0)).save(image_path)
    captured = {}

    def capture_export(**kwargs):
        captured.update(kwargs)

    with patch.object(vector_processing, "export_processed_layers", side_effect=capture_export), patch.object(
        vector_processing, "save_vector_output"
    ):
        vector_processing.raster_to_puzzle_and_lightburn(
            raster_image_path=image_path,
            output_svg_path=str(tmp_path / "cropped.svg"),
            new_height=0,
            new_width=12,
            lb_project_instance=object(),
            TARGET_COLORS={
                "#000000": (0, 0, "Black"),
                "#FF0000": (0, 2, "Red"),
            },
            scale_factor=1,
            image_preset="cartoon",
            abstract_filter="none",
            export_lightburn=False,
            crop_shape="oval",
        )

    boundary = vector_processing.artwork_crop_geometry(12, 8, "oval")
    assert captured["processed_layers"]
    for geometry in captured["processed_layers"].values():
        assert geometry.difference(boundary).area <= 1e-9
    assert captured["black_lightburn_geometry"].difference(boundary).area <= 1e-9


def test_staging_ui_uses_applied_crop_for_preview_upload_and_shape_metadata():
    source = Path("serverless_web/index.html").read_text(encoding="utf-8")

    assert 'id="cropShape"' in source
    assert 'id="applyCrop" type="button" disabled>Crop preview</button>' in source
    assert 'id="cropTransparency" type="button" disabled>Crop transparency</button>' in source
    assert all(f'<option value="{shape}">' in source for shape in ("rectangle", "square", "oval", "circle"))
    assert "function effectiveArtworkFile()" in source
    assert "const art=effectiveArtworkFile()" in source
    assert "file=effectiveArtworkFile()" in source
    assert "crop_shape:appliedCropShape" in source
    assert "data[offset+3]===0" in source
    assert ".quant-preview-canvas.transparency-grid" in source
    assert "appliedCropShape==='transparency'||document.querySelector('#whiteIs').value==='unengraved'" in source
    assert ".crop-canvas{display:block;width:auto;height:auto;max-width:100%;max-height:520px" in source
    assert "function cropHandleAt(point)" in source
    assert "cropDragMode='move'" in source
    assert "cropDragMode='resize'" in source
    assert "It will apply automatically on submission" in source
    assert "await applyArtworkCrop()" in source
    assert "function applyTransparencyCrop()" in source
    assert "Exterior transparency and enclosed transparent holes will produce no geometry." in source


def test_crop_shape_is_validated_and_forwarded_to_worker():
    api_source = Path("serverless_api/handler.py").read_text(encoding="utf-8")
    service_source = Path("services.py").read_text(encoding="utf-8")
    cli_source = Path("lib/Material_Library.py").read_text(encoding="utf-8")

    assert 'data["crop_shape"] = crop_shape' in api_source
    assert '"transparency"' in api_source
    assert 'str(data.get("crop_shape", "")).strip().lower()' in service_source
    assert "crop_shape=crop_shape" in cli_source
    assert '"transparency"' in cli_source

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_rasterizer_exposes_matching_presets_custom_controls_and_browser_preview():
    page = (ROOT / "serverless_web" / "index.html").read_text(encoding="utf-8")

    for value in ("balanced", "hue", "shades", "closest", "custom"):
        assert f'<option value="{value}">' in page
    for control_id in (
        "matchingHue", "matchingSaturation", "matchingLightness",
        "generateQuantPreview", "quantPreviewCanvas", "quantPreviewCounts",
    ):
        assert f'id="{control_id}"' in page
    assert "function quantizePreviewPixels(" in page
    assert "context.getImageData(" in page
    assert "The preview is generated entirely in this browser" in page


def test_matching_settings_are_submitted_validated_and_forwarded_to_worker():
    page = (ROOT / "serverless_web" / "index.html").read_text(encoding="utf-8")
    handler = (ROOT / "serverless_api" / "handler.py").read_text(encoding="utf-8")
    cli = (ROOT / "lib" / "Material_Library.py").read_text(encoding="utf-8")
    processing = (ROOT / "lib" / "vector_processing.py").read_text(encoding="utf-8")

    assert "abstract_filter_parameters:JSON.stringify(filterParameters()),...colorMatchingParameters()" in page
    assert 'matching_mode not in {"balanced", "hue", "shades", "closest", "custom"}' in handler
    assert "color_matching=color_matching" in cli
    assert "def resolve_color_matching(" in processing
    assert "color_matching=color_matching" in processing

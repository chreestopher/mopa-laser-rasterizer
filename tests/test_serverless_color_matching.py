from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_rasterizer_exposes_matching_presets_custom_controls_and_browser_preview():
    page = (ROOT / "serverless_web" / "index.html").read_text(encoding="utf-8")

    for value in ("balanced", "hue", "shades", "closest", "custom"):
        assert f'<option value="{value}">' in page
    for control_id in (
        "matchingHue", "matchingSaturation", "matchingLightness",
        "generateQuantPreview", "quantPreviewCanvas", "quantPreviewCounts",
        "quantPreviewRulerX", "quantPreviewRulerY",
    ):
        assert f'id="{control_id}"' in page
    assert "function quantizePreviewPixels(" in page
    assert "function rasterPreviewDimensions(" in page
    assert "height===0&&width!==0" in page
    assert "width===0&&height!==0" in page
    assert "Math.trunc(sourceHeight*width/sourceWidth)" in page
    assert "Math.trunc(sourceWidth*height/sourceHeight)" in page
    assert "640/Math.max(width,height)" not in page
    assert "processing pixels" in page
    assert "mm engraving" in page
    assert "function niceRulerStep(" in page
    assert "return Math.max(1,multiple*power)" in page
    assert "maximumFractionDigits:0" in page
    assert "endpointGap>step*.55" in page
    assert ".quant-ruler-horizontal .quant-ruler-tick:nth-child(even):not(:last-child){display:none}" in page
    assert "function renderPreviewRulers(" in page
    assert "renderPreviewRulers(widthMm,heightMm)" in page
    assert "context.getImageData(" in page
    assert "The preview is generated entirely in this browser" in page


def test_quantized_preview_uses_only_currently_enabled_swatches():
    page = (ROOT / "serverless_web" / "index.html").read_text(encoding="utf-8")

    assert "function paletteEntrySelectionKey(entry)" in page
    assert "selectedPaletteHexes.has(key)" in page
    assert "const key=paletteEntrySelectionKey(entry)" in page
    assert "hex=String(entry.display_hex||entry.hex||'').toUpperCase()" in page
    assert "output.hidden=true" in page
    assert "currently enabled swatches" in page


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

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_spiralgrap_page_uses_external_assets_and_classic_controls():
    page = read("serverless_web/spiralgraph.html")
    client = read("serverless_web/spiralgraph.js")
    drawing_editor = read("serverless_web/spiralgraph/drawing-editor-v1.js")
    assert 'src="/spiralgraph.js?v=9"' in page
    assert 'href="/spiralgraph.css?v=3"' in page
    assert "Track plate" in drawing_editor and "Rolling gear" in drawing_editor and "Pen hole" in drawing_editor
    assert "Starting mark" in drawing_editor and "Rolling position" in drawing_editor
    assert "output_mode" in drawing_editor and "fill_thickness_mm" in drawing_editor
    assert "Line / Cut · open path" in drawing_editor and "Filled ribbon · closed path" in drawing_editor
    assert 'api("/spiralgraph/jobs"' in client


def test_spiralgraph_can_use_saved_color_palette_swatches_for_preview_and_output_layers():
    page = read("serverless_web/spiralgraph.html")
    client = read("serverless_web/spiralgraph.js")
    palette_routing = read("serverless_web/spiralgraph/palette-routing-v1.js")
    drawing_editor = read("serverless_web/spiralgraph/drawing-editor-v1.js")
    canvas_preview = read("serverless_web/spiralgraph/canvas-preview-v1.js")
    styles = read("serverless_web/spiralgraph.css")
    api = read("serverless_api/handler.py")
    backend = read("lib/spiralgrap.py")
    assert 'id="colorPalette"' in page
    assert 'data-field="swatch_hex" type="radio"' in drawing_editor
    assert '<div class="layer-heading-swatches">${swatchPicker(layer,index)}</div>' in drawing_editor
    assert 'from "./spiralgraph/palette-routing-v1.js"' in client
    assert "function paletteSwatches()" in palette_routing
    assert "function applySwatchMode(layer)" in palette_routing
    assert "context.strokeStyle=previewColor(layer,index)" in canvas_preview
    assert "color_palette_id" in client and "color_palette_id" in api
    assert "community_material_swatch" in api
    assert 'layer.get("lightburn_index")' in backend
    assert 'layer.get("laser_setting")' in backend
    assert "allow_reuse=bool(palette_setting)" in backend
    assert 'layer.get("swatch_hex") or COLORS' in backend
    assert "function payloadLayer(source)" in client
    assert "SPIRALGRAPH_BUILTIN_COLORS" in api
    assert 'layer.pop("swatch_hex", None)' not in api
    assert "Choose one of the built-in SpiralGraph colors" in api
    assert ".preview-swatches" in styles
    assert ".layer-heading-swatches" in styles
    assert ".layer-controls{grid-template-columns:minmax(0,1fr);width:100%}" in styles
    assert ".layer-heading-swatches .preview-swatches>div{flex-wrap:wrap;width:100%;overflow:visible}" in styles


class SpiralGraphHardwarePreviewTests(unittest.TestCase):
    def test_virtual_hardware_is_live_accessible_and_synchronized(self):
        page = read("serverless_web/spiralgraph.html")
        client = read("serverless_web/spiralgraph.js")
        geometry = read("serverless_web/spiralgraph/geometry-v1.js")
        hardware = read("serverless_web/spiralgraph/hardware-preview-v1.js")
        drawing_editor = read("serverless_web/spiralgraph/drawing-editor-v1.js")
        styles = read("serverless_web/spiralgraph.css")
        self.assertIn('id="hardwarePreview"', page)
        for label in ("Track plate", "Rolling gear and pencil holes", "Assembled position"):
            self.assertIn(label, page)
        self.assertIn('role="radiogroup"', page)
        self.assertIn('aria-live="polite"', page)
        self.assertIn("PEN_HOLE_FACTORS=[0,.2,.36,.52,.68,.82,.94]", geometry)
        self.assertIn("function rollingModel(layer)", geometry)
        self.assertIn("function rollingState(model,distance)", geometry)
        self.assertIn('from "./geometry-v1.js"', drawing_editor)
        self.assertIn('from "./spiralgraph/hardware-preview-v1.js"', client)
        self.assertIn(
            "createHardwarePreview({getActiveLayer:()=>getLayers()[getActiveLayerIndex()],getActiveLayerIndex,schedulePreview})",
            client,
        )
        self.assertIn("function selectPenHole(hole,announce=true)", hardware)
        for behavior in ('role:"radio"', '"aria-checked"', 'focusable:"true"', "ArrowRight", "ArrowLeft", 'event.key==="Home"', 'event.key==="End"'):
            self.assertIn(behavior, hardware)
        self.assertIn('[data-field="pen_hole"]', hardware)
        self.assertIn("createElementNS", hardware)
        self.assertIn("DOMParser", geometry)
        self.assertNotIn("host.innerHTML", client)
        self.assertNotIn("host.innerHTML", geometry)
        self.assertNotIn("function renderTrackHardware", client)
        self.assertNotIn("function selectPenHole", client)
        self.assertIn(".hardware-hole-target", styles)
        self.assertIn("touch-action:manipulation", styles)
        self.assertIn(".light-machine .hardware-grid svg", styles)
        self.assertIn("@media(max-width:800px)", styles)

    def test_curve_and_hardware_share_precomputed_geometry(self):
        client = read("serverless_web/spiralgraph.js")
        geometry = read("serverless_web/spiralgraph/geometry-v1.js")
        curve = geometry.split("function curvePoints(layer)", 1)[1].split("function bounds", 1)[0]
        self.assertIn("const model=rollingModel(layer)", curve)
        self.assertIn("rollingState(model", curve)
        self.assertNotIn("trackPoints(", curve)
        self.assertNotIn("cumulative(", curve)
        self.assertIn("stableHardwareDistance", geometry)
        self.assertIn("Number.isFinite", geometry)
        self.assertIn("Teeth are schematic", read("serverless_web/spiralgraph.html"))


class SpiralGraphCanvasPreviewTests(unittest.TestCase):
    def test_selected_and_stacked_canvas_preview_owns_frame_scheduling(self):
        client = read("serverless_web/spiralgraph.js")
        canvas_preview = read("serverless_web/spiralgraph/canvas-preview-v1.js")
        self.assertIn('from "./spiralgraph/canvas-preview-v1.js"', client)
        self.assertIn("createCanvasPreview({colors:COLORS", client)
        self.assertIn("function schedulePreview(){canvasPreview.schedulePreview()}", client)
        self.assertIn('from "./geometry-v1.js"', canvas_preview)
        self.assertIn("function previewColor(layer,index)", canvas_preview)
        self.assertIn("function drawLayer(canvas,layer,index,alpha=1,clear=false)", canvas_preview)
        self.assertIn("cancelAnimationFrame(previewFrame)", canvas_preview)
        self.assertIn("previewFrame=requestAnimationFrame", canvas_preview)
        self.assertIn('drawLayer($("#activePreview")', canvas_preview)
        self.assertIn('const canvas=$("#stackPreview")', canvas_preview)
        self.assertIn("renderHardware()", canvas_preview)
        self.assertNotIn("function previewColor", client)
        self.assertNotIn("function drawLayer", client)
        self.assertNotIn("requestAnimationFrame", client)


def test_spiralgrap_is_deployed_linked_documented_and_history_backed():
    deploy = read("dev_setup/deploy_serverless_staging_web.sh")
    shell = read("serverless_web/staging-shell.js")
    landing = read("templates/experimental_laboratories.html")
    docs = read("routes/docs.py")
    api = read("serverless_api/handler.py")
    worker = read("worker.py")
    template = read("ecs/serverless-staging-web.yaml")
    history = read("serverless_web/history.js")
    for filename in ("spiralgraph.html", "spiralgraph.js", "spiralgraph.css", "spiralgraph/geometry-v1.js", "spiralgraph/hardware-preview-v1.js", "spiralgraph/canvas-preview-v1.js", "spiralgraph/drawing-editor-v1.js", "spiralgraph/state-v1.js", "spiralgraph/palette-routing-v1.js"):
        assert filename in deploy
    assert '"/spiralgraph.html"' in shell and 'href="/spiralgraph.html"' in landing
    assert '"spiralgraph-lab": _page(' in docs
    assert '"/spiralgraph/jobs", "/spiralgrap/jobs"' in api
    assert "RouteKey: POST /spiralgraph/jobs" in template
    assert "RouteKey: POST /spiralgrap/jobs" in template
    assert "SpiralGrapJobsRoute:" in template
    assert "SpiralGrapLegacyJobsRoute:" not in template
    assert 'url=/spiralgraph.html' in read("serverless_web/spiralgrap.html")
    assert 'payload.get("job_type") == "spiralgrap"' in worker
    assert "run_spiralgrap_job" in worker
    assert 'spiralgrap:"SpiralGraph Lab"' in history


def test_spiralgrap_validates_custom_svg_and_processing_modes_on_both_sides():
    client = read("serverless_web/spiralgraph.js")
    drawing_editor = read("serverless_web/spiralgraph/drawing-editor-v1.js")
    api = read("serverless_api/handler.py")
    backend = read("lib/spiralgrap.py")
    for field in ("track", "gear_teeth", "pen_hole", "side", "start_mark", "direction", "output_mode", "fill_thickness_mm", "swatch_hex"):
        assert (field in client or field in drawing_editor) and field in api and field in backend
    assert "file.size>65536" in drawing_editor
    assert 'expected_type, required' in api
    assert 'closed=False' in backend
    assert "_fill_rings" in backend

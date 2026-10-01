from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_mandala_lab_uses_external_assets_and_accessible_previews():
    page = read("serverless_web/mandala.html")
    assert 'src="/mandala.js?v=14"' in page
    assert 'href="/mandala.css?v=1"' in page
    assert "<script>" not in page
    assert 'id="layerPreviewSlider"' in page and 'type="range"' in page
    assert 'id="layerPreviewName"' in page and 'id="layerPreviewPosition"' in page
    assert 'id="activePreview"' in page and 'aria-label="Selected mandala layer preview"' in page
    assert 'id="stackPreview"' in page and 'aria-label="Stacked mandala assembly preview"' in page
    assert "Fully stacked assembly" in page
    assert "Generate projects for review" in page


def test_mandala_lab_is_linked_and_deployed():
    shell = read("serverless_web/staging-shell.js")
    landing = read("templates/experimental_laboratories.html")
    deploy = read("dev_setup/deploy_serverless_staging_web.sh")
    assert '"/mandala.html"' in shell
    assert 'href="/mandala.html"' in landing
    assert '$BUILD_DIR/seo/mandala.html' in deploy
    for filename in ("mandala.js", "mandala.css", "mandala/state-v1.js", "mandala/palette-routing-v1.js", "mandala/geometry-v1.js", "mandala/preview-v1.js", "mandala/asset-constraints-v1.js", "mandala/job-lifecycle-v1.js", "mandala/layer-editor-v1.js"):
        assert f'serverless_web/{filename}' in deploy


def test_mandala_lab_is_documented_and_in_generated_sitemap():
    docs = read("routes/docs.py")
    seo = read("dev_setup/build_serverless_seo.py")
    assert '"layered-mandala-lab": _page(' in docs
    assert '("Layered Mandala Lab", ["layered-mandala-lab"])' in docs
    assert 'write_static_page(\n    "mandala.html"' in seo
    assert '    "mandala.html",' in seo


def test_mandala_jobs_are_authenticated_history_backed_worker_jobs():
    api = read("serverless_api/handler.py")
    template = read("ecs/serverless-staging-web.yaml")
    worker = read("worker.py")
    history = read("serverless_web/history.js")
    assert 'path == "/mandala/jobs"' in api
    assert '"job_type": "layered_mandala"' in api
    assert "RouteKey: POST /mandala/jobs" in template
    assert 'payload.get("job_type") == "layered_mandala"' in worker
    assert "run_layered_mandala_job" in worker
    assert 'layered_mandala:"Layered Mandala Lab"' in history


def test_mandala_client_defaults_cut_role_and_limits_custom_svg():
    client = read("serverless_web/mandala.js")
    layer_editor = read("serverless_web/mandala/layer-editor-v1.js")
    job_lifecycle = read("serverless_web/mandala/job-lifecycle-v1.js")
    palette_routing = read("serverless_web/mandala/palette-routing-v1.js")
    asset_constraints = read("serverless_web/mandala/asset-constraints-v1.js")
    assert 'defaultRoleEntry(library,material,"Cut")' in palette_routing
    assert 'file.size>65536' in asset_constraints
    assert 'from "./mandala/asset-constraints-v1.js"' in client
    assert 'layers.length>=12' in layer_editor
    assert 'api("/mandala/jobs"' in job_lifecycle


def test_mandala_job_lifecycle_owns_payload_auth_submission_polling_and_resume():
    client = read("serverless_web/mandala.js")
    lifecycle = read("serverless_web/mandala/job-lifecycle-v1.js")
    assert 'from "./mandala/job-lifecycle-v1.js"' in client
    assert "export function createMandalaJobLifecycle(" in lifecycle
    for function in ("payloadLayer", "payload", "tokenExpiresSoon", "refreshSession", "api", "outputsHtml", "poll", "bind", "bootstrap", "start"):
        assert f"function {function}(" in lifecycle
        assert f"function {function}(" not in client
    assert 'api("/mandala/jobs"' in lifecycle
    assert 'new URLSearchParams(location.search).get("task")' in lifecycle
    assert "setTimeout(()=>poll(taskId),3000)" in lifecycle
    assert "_image,_imagePromise,...layer" in lifecycle


def test_mandala_asset_constraints_own_svg_safety_and_project_dimensions():
    client = read("serverless_web/mandala.js")
    constraints = read("serverless_web/mandala/asset-constraints-v1.js")
    assert "export async function normalizeSvg(" in constraints
    assert "export function createMandalaAssetConstraints(" in constraints
    for function in ("normalizeSvg", "syncProjectDimensions", "handleCustomFileChange", "bindEvents"):
        assert f"function {function}(" in constraints
        assert f"function {function}(" not in client
    for message in (
        "Choose an SVG file.",
        "Custom SVG files must be no larger than 64 KB.",
        "The custom SVG could not be read.",
        "Embedded or external SVG content is not supported.",
    ):
        assert message in constraints
    assert "diameter*.15" in constraints
    assert "diameter*.08" in constraints


def test_mandala_preview_uses_slider_and_updates_live_with_layer_settings():
    client = read("serverless_web/mandala.js")
    layer_editor = read("serverless_web/mandala/layer-editor-v1.js")
    preview = read("serverless_web/mandala/preview-v1.js")
    assert '$("#layerPreviewSlider").addEventListener("input"' in layer_editor
    assert "function syncPreviewSelector()" in layer_editor
    assert "syncPreviewSelector();schedulePreview()" in layer_editor
    assert 'data-action="select"' not in layer_editor
    assert 'from "./mandala/preview-v1.js"' in client
    assert "export function createMandalaPreview(" in preview
    for function in ("schedulePreview", "customImage", "drawLayer", "drawPreviews"):
        assert f"function {function}(" in preview
        assert f"function {function}(" not in client
    assert 'for(const id of ["activePreview","stackPreview"])' in preview
    assert 'drawLayer(query("#activePreview"),layers[activeLayer],activeLayer,1)' in preview
    assert 'drawLayer(query("#stackPreview"),layer,index,.38)' in preview


def test_mandala_geometry_module_owns_motifs_flow_and_support_bridges():
    client = read("serverless_web/mandala.js")
    preview = read("serverless_web/mandala/preview-v1.js")
    geometry = read("serverless_web/mandala/geometry-v1.js")
    assert 'from "./geometry-v1.js"' in preview
    for function in (
        "builtInPath",
        "drawMotif",
        "supportBridgePath",
        "flowingPetalPath",
        "drawFlowingPattern",
        "drawComposedMotifs",
    ):
        assert f"export function {function}(" in geometry
        assert f"function {function}(" not in client
        assert f"function {function}(" not in preview


def test_each_mandala_layer_can_be_randomized_or_reset_to_defaults():
    client = read("serverless_web/mandala.js")
    layer_editor = read("serverless_web/mandala/layer-editor-v1.js")
    state = read("serverless_web/mandala/state-v1.js")
    assert 'data-action="randomize">Randomize' in layer_editor
    assert 'data-action="reset">Reset to defaults' in layer_editor
    assert 'from "./state-v1.js"' in layer_editor
    assert "export function newLayer(index)" in state
    assert "export function randomizedLayer(layer,index,diameterValue,random=Math.random)" in state
    assert "export function resetLayer(layer,index)" in state
    assert "export function duplicateLayer(layer)" in state
    assert "function newLayer(index)" not in client
    assert "function randomizedLayer(layer,index)" not in client
    assert 'if(action==="randomize")' in layer_editor
    assert 'if(action==="reset")' in layer_editor


def test_mandala_layer_editor_owns_controls_collection_and_preview_selection():
    client = read("serverless_web/mandala.js")
    layer_editor = read("serverless_web/mandala/layer-editor-v1.js")
    assert 'from "./mandala/layer-editor-v1.js"' in client
    assert "export function createMandalaLayerEditor(" in layer_editor
    for function in ("numberControl", "layerCard", "syncPreviewSelector", "renderLayers", "resetLayers", "getLayers", "getActiveLayer", "bind"):
        assert f"function {function}(" in layer_editor
        assert f"function {function}(" not in client
    for action in ("randomize", "reset", "duplicate", "remove", "up", "down"):
        assert f'action==="{action}"' in layer_editor
    assert 'event.target.type==="checkbox"?event.target.checked:event.target.type==="number"?Number(event.target.value):event.target.value' in layer_editor
    assert '$("#diameter").addEventListener("input",schedulePreview)' in layer_editor


def test_mandala_support_labels_state_connectivity_truthfully():
    layer_editor = read("serverless_web/mandala/layer-editor-v1.js")
    page = read("serverless_web/mandala.html")
    assert "Rim and hub; motifs may remain loose" in layer_editor
    assert "Automatic bridges — one piece" in layer_editor
    assert "Fully connected — one piece" in layer_editor
    assert "Generate projects for review" in page


def test_mandala_support_and_openwork_controls_are_wired_end_to_end():
    layer_editor = read("serverless_web/mandala/layer-editor-v1.js")
    api = read("serverless_api/handler.py")
    backend = read("lib/mandala.py")
    docs = read("routes/docs.py")
    for field in (
        "support_sweep_degrees",
        "bridge_wave_amount",
        "bridge_wave_amplitude_mm",
        "bridge_wave_position",
        "layer_openness",
        "opening_inner_ratio",
        "opening_rotation_degrees",
        "rim_style",
        "ornament_style",
        "motif_composition",
        "motif_radial_position",
        "motif_tangential_position",
        "fragment_scale",
        "flow_amount",
        "petal_fullness",
        "tip_sharpness",
        "curl_degrees",
        "band_overlap",
        "mirror_wedges",
    ):
        assert field in layer_editor
        assert field in api
        assert field in backend
    assert "Support sweep angle" in layer_editor
    assert "Layer openness" in layer_editor
    assert "Petal crown" in layer_editor
    assert "Billowing scallops" in layer_editor
    assert "Mirrored flowing wedge pairs" in layer_editor
    assert "Whole motifs + mirrored fragments" in layer_editor
    assert "Kaleidoscope sliced fragments" in layer_editor
    assert "Support Sweep Angle" in docs
    assert "Layer Openness" in docs

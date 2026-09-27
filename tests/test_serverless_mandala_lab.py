from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_mandala_lab_uses_external_assets_and_accessible_previews():
    page = read("serverless_web/mandala.html")
    assert 'src="/mandala.js?v=2"' in page
    assert 'href="/mandala.css?v=1"' in page
    assert "<script>" not in page
    assert 'id="activePreview"' in page and 'aria-label="Active mandala layer preview"' in page
    assert 'id="stackPreview"' in page and 'aria-label="Stacked mandala assembly preview"' in page
    assert "Generate projects for review" in page


def test_mandala_lab_is_linked_and_deployed():
    shell = read("serverless_web/staging-shell.js")
    landing = read("templates/experimental_laboratories.html")
    deploy = read("dev_setup/deploy_serverless_staging_web.sh")
    assert '"/mandala.html"' in shell
    assert 'href="/mandala.html"' in landing
    assert '$BUILD_DIR/seo/mandala.html' in deploy
    for filename in ("mandala.js", "mandala.css"):
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
    assert 'defaultRoleEntry(library,material,"Cut")' in client
    assert 'file.size>65536' in client
    assert 'layers.length>=12' in client
    assert 'api("/mandala/jobs"' in client


def test_mandala_support_labels_state_connectivity_truthfully():
    client = read("serverless_web/mandala.js")
    page = read("serverless_web/mandala.html")
    assert "Rim and hub; motifs may remain loose" in client
    assert "Automatic bridges — one piece" in client
    assert "Fully connected — one piece" in client
    assert "Generate projects for review" in page

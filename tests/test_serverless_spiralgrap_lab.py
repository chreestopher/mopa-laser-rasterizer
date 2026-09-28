from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_spiralgrap_page_uses_external_assets_and_classic_controls():
    page = read("serverless_web/spiralgraph.html")
    client = read("serverless_web/spiralgraph.js")
    assert 'src="/spiralgraph.js?v=1"' in page
    assert 'href="/spiralgraph.css?v=1"' in page
    assert "Track plate" in client and "Rolling gear" in client and "Pen hole" in client
    assert "Starting mark" in client and "Rolling position" in client
    assert "output_mode" in client and "fill_thickness_mm" in client
    assert "Line / Cut · open path" in client and "Filled ribbon · closed path" in client
    assert 'api("/spiralgraph/jobs"' in client


def test_spiralgrap_is_deployed_linked_documented_and_history_backed():
    deploy = read("dev_setup/deploy_serverless_staging_web.sh")
    shell = read("serverless_web/staging-shell.js")
    landing = read("templates/experimental_laboratories.html")
    docs = read("routes/docs.py")
    api = read("serverless_api/handler.py")
    worker = read("worker.py")
    template = read("ecs/serverless-staging-web.yaml")
    history = read("serverless_web/history.js")
    for filename in ("spiralgraph.html", "spiralgraph.js", "spiralgraph.css"):
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
    api = read("serverless_api/handler.py")
    backend = read("lib/spiralgrap.py")
    for field in ("track", "gear_teeth", "pen_hole", "side", "start_mark", "direction", "output_mode", "fill_thickness_mm"):
        assert field in client and field in api and field in backend
    assert "file.size>65536" in client
    assert 'expected_type, required' in api
    assert 'closed=False' in backend
    assert "_fill_rings" in backend

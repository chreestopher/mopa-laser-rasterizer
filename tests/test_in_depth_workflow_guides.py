import subprocess
import sys
import tempfile
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_in_depth_guides_build_and_cover_the_complete_workflows():
    with tempfile.TemporaryDirectory() as temporary:
        output = Path(temporary) / "docs"
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "dev_setup" / "build_serverless_docs.py"),
                str(output),
                "https://staging.example.com",
            ],
            check=True,
        )

        index = (output / "index.html").read_text(encoding="utf-8")
        fauxlogram = (output / "fauxlogram-tutorial").read_text(encoding="utf-8")
        rasterizer = (output / "multi-geometry-rasterizer-guide").read_text(encoding="utf-8")
        release_story = (ROOT / "serverless_web" / "release-story.html").read_text(encoding="utf-8")

        assert 'href="/docs/fauxlogram-tutorial"' in index
        assert 'href="/docs/multi-geometry-rasterizer-guide"' in index
        assert "In-depth workflow guide" in fauxlogram
        assert "STAGE " in fauxlogram
        assert "First method: launch a Krasnow Color Grating test" in fauxlogram
        assert "Go deeper: generate a Fauxlographic Etching Lab grid" in fauxlogram
        assert "Advanced method: reveal Krasnow Grating Geometry Style" in fauxlogram
        assert "Entire Artwork radial" in fauxlogram
        assert "Each Shape radial" in fauxlogram
        assert "not a true wavefront hologram" in fauxlogram
        assert "Prepare the LightBurn Material Library for import or upload" in rasterizer
        assert "Rename each entry" in rasterizer
        assert "Description" in rasterizer
        assert "Crop transparency" in rasterizer
        assert "Choose by swatch under Geometry Style" in rasterizer
        assert "Fauxlogram Gradient Scope" in rasterizer
        assert "Center to Edge" in rasterizer
        assert "positive engraving area" in rasterizer
        assert 'href="/docs/fauxlogram-tutorial"' in release_story
        assert 'href="/docs/multi-geometry-rasterizer-guide"' in release_story


def test_staging_release_story_deployment_uploads_png_screenshots():
    deploy = (ROOT / "dev_setup" / "deploy_serverless_staging_web.sh").read_text(encoding="utf-8")

    assert '*.png) media_type="image/png"' in deploy
    assert '*.svg) media_type="image/svg+xml"' in deploy


def test_fauxlographic_lab_uses_new_public_url_and_keeps_classic_redirect():
    deploy = (ROOT / "dev_setup" / "deploy_serverless_staging_web.sh").read_text(encoding="utf-8")
    redirect_page = (ROOT / "serverless_web" / "holographic-redirect.html").read_text(encoding="utf-8")
    lab_page = (ROOT / "serverless_web" / "holographic.html").read_text(encoding="utf-8")
    routes = (ROOT / "routes" / "home.py").read_text(encoding="utf-8")

    assert 'web/fauxlographic.html' in deploy
    assert 'web/holographic.html' in deploy
    assert 'url=/fauxlographic.html' in redirect_page
    assert 'location.replace(\'/fauxlographic.html\'' in redirect_page
    assert '<link rel="canonical" href="/fauxlographic.html">' in lab_page
    assert '@routes.route("/fauxlographic-etching")' in routes
    assert '@routes.route("/holographic-etching")' in routes
    assert 'redirect(f"/fauxlographic-etching{query}", code=308)' in routes


def test_release_story_referenced_media_files_exist():
    story = (ROOT / "serverless_web" / "release-story.html").read_text(encoding="utf-8")
    media_paths = set(
        re.findall(r'(?:src|poster)="(/release-story-media/[^"]+)"', story)
    )

    assert media_paths
    for media_path in media_paths:
        assert (ROOT / "serverless_web" / media_path.lstrip("/")).is_file(), media_path

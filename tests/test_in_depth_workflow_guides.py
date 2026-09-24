import subprocess
import sys
import tempfile
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_rasterizer_home_links_to_workflow_guides_before_inputs():
    homes = (
        ((ROOT / "templates" / "index.html").read_text(encoding="utf-8"), '<!-- Form Section -->'),
        ((ROOT / "serverless_web" / "index.html").read_text(encoding="utf-8"), '<form id="job"'),
    )

    for home, input_marker in homes:
        guide_panel = home.split('<nav class="rasterizer-guide-links"', 1)[1].split("</nav>", 1)[0]
        assert home.index('<nav class="rasterizer-guide-links"') < home.index(input_marker)
        for slug in (
            "fauxlogram-tutorial",
            "multi-geometry-rasterizer-guide",
            "manual-krasnow-geometry-workflow",
        ):
            assert f'href="/docs/{slug}"' in guide_panel
        assert 'href="/docs/color-layers"' not in guide_panel


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
        manual_krasnow = (output / "manual-krasnow-geometry-workflow").read_text(encoding="utf-8")
        release_story = (ROOT / "serverless_web" / "release-story.html").read_text(encoding="utf-8")

        assert 'href="/docs/fauxlogram-tutorial"' in index
        assert 'href="/docs/multi-geometry-rasterizer-guide"' in index
        assert 'href="/docs/manual-krasnow-geometry-workflow"' in index
        assert "MOPA Madness: The Wizzard of Awes" in fauxlogram
        assert "Geometric Alchemy: The Wizzard of Awes" in rasterizer
        assert "Reproducing Krasnow Grating Geometry by Hand" in manual_krasnow
        assert "In-depth workflow guide" in manual_krasnow
        assert "STAGE " in manual_krasnow
        assert "docs-markdown-table" in manual_krasnow
        assert "gradient_value = 165" in manual_krasnow
        assert "The three decisions made for every cell" in manual_krasnow
        assert "wizardlogo.png" in (ROOT / "serverless_web" / "staging-shell.js").read_text(encoding="utf-8")
        assert "wizardlogo.png" in (ROOT / "templates" / "_machine_chrome.html").read_text(encoding="utf-8")
        assert (ROOT / "static" / "docs" / "wizardlogo.png").is_file()
        assert "In-depth workflow guide" in fauxlogram
        assert "STAGE " in fauxlogram
        assert "First method: launch a Krasnow Grating test" in fauxlogram
        assert "Go deeper: generate a Fauxlographic Etching Lab grid" in fauxlogram
        assert "smaller refinement grid" not in fauxlogram
        assert "cells with no apparent visual difference from others" in fauxlogram
        assert "Explore composable Krasnow Geometry" in fauxlogram
        assert "Entire Artwork radial" in fauxlogram
        assert "Each Shape radial" in fauxlogram
        assert "not a true wavefront hologram" in fauxlogram
        assert "Configure it as a LightBurn Cut/Line operation, not Fill or Offset Fill" in fauxlogram
        assert "Additional sublayers, if present, are ignored" in fauxlogram
        assert "best combination of engraving quality and time on the laser when Flood Fill is enabled" in fauxlogram
        assert "parent Fauxlographic" not in fauxlogram
        assert "Fauxlographic parent setting" not in fauxlogram
        assert "Prepare the LightBurn Material Library for import or upload" in rasterizer
        assert "copy it into a separate backup location without altering it" in rasterizer
        assert "make all Rasterizer-specific edits only in the working copy" in rasterizer
        assert "best combination of engraving quality and time on the laser when Flood Fill is enabled" in rasterizer
        assert "Rename each entry" in rasterizer
        assert "Description" in rasterizer
        assert "can use matching entries with any thickness value" in rasterizer
        assert "no-thickness" not in fauxlogram.lower()
        assert "no-thickness" not in rasterizer.lower()
        assert "Crop transparency" in rasterizer
        assert "Choose by swatch under Geometry Style" in rasterizer
        assert "download whichever output files you want or need" in rasterizer
        assert "Download the SVG first" not in rasterizer
        assert "also appear inside it as knockout holes" in fauxlogram
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
        asset_path = media_path.partition("?")[0]
        assert (ROOT / "serverless_web" / asset_path.lstrip("/")).is_file(), media_path


def test_release_story_media_placeholders_are_retained_only_as_comments():
    story = (ROOT / "serverless_web" / "release-story.html").read_text(encoding="utf-8")
    visible_story = re.sub(r"<!--.*?-->", "", story, flags=re.DOTALL)

    assert story.count("Future media slot:") == 3
    assert 'class="image-needed"' not in visible_story
    assert 'class="update-needed"' not in visible_story


def test_release_story_repeatability_videos_have_poster_images():
    story = (ROOT / "serverless_web" / "release-story.html").read_text(encoding="utf-8")
    section = story.split('<h2 id="was-heads-just-lucky">', 1)[1].split("<hr>", 1)[0]
    videos = re.findall(r"<video\b[^>]*>", section)

    assert len(videos) == 6
    assert all('poster="/release-story-media/' in video for video in videos)


def test_release_story_pairs_color_lab_measurement_and_selection_captures():
    story = (ROOT / "serverless_web" / "release-story.html").read_text(encoding="utf-8")

    assert '<div class="media-gallery media-pair">' in story
    assert "/release-story-media/ui-color-lab-photograph-alignment-blue.png" in story
    assert "/release-story-media/ui-color-lab-swatch-selection-blue.png" in story
    assert ".media-gallery.media-pair .media-block:first-child{grid-column:auto}" in story


def test_release_story_pairs_glyph_source_and_lightburn_output():
    story = (ROOT / "serverless_web" / "release-story.html").read_text(encoding="utf-8")

    assert "/release-story-media/glyph-skulls-source.png" in story
    assert "/release-story-media/glyph-skulls-lightburn.png" in story
    assert "Source artwork" in story
    assert "Skull glyph geometry in LightBurn" in story


def test_release_story_visually_compares_fauxlographic_palette_and_krasnow():
    story = (ROOT / "serverless_web" / "release-story.html").read_text(encoding="utf-8")

    assert "/release-story-media/fauxlographic-vs-krasnow.mp4" in story
    assert "Fauxlographic Palette artwork is driven by measured laser settings" in story
    assert "Krasnow Grating combines laser settings with newly generated geometry" in story

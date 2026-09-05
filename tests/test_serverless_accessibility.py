import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_rasterizer_primary_controls_have_programmatic_labels():
    page = (ROOT / "serverless_web" / "index.html").read_text(encoding="utf-8")

    for control_id in (
        "artwork",
        "materialChoice",
        "materialFile",
        "materialName",
        "pixel",
        "width",
        "height",
        "imagePreset",
    ):
        assert f'for="{control_id}"' in page


def test_depthmap_source_file_has_an_accessible_name():
    template = (ROOT / "templates" / "depthmap_generator.html").read_text(encoding="utf-8")

    assert 'id="depth_input"' in template
    assert 'aria-label="Source image file"' in template


def test_staging_pages_do_not_nest_main_landmarks(tmp_path):
    color_lab = (ROOT / "serverless_web" / "color-lab.html").read_text(encoding="utf-8")
    assert "<main" not in color_lab

    built_depthmap = tmp_path / "depthmap.html"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "dev_setup" / "build_serverless_depthmap.py"),
            str(ROOT / "templates" / "depthmap_generator.html"),
            str(built_depthmap),
        ],
        check=True,
    )
    assert "<main" not in built_depthmap.read_text(encoding="utf-8")

    shell = (ROOT / "serverless_web" / "staging-shell.js").read_text(encoding="utf-8")
    assert 'pageShell = document.createElement("main")' in shell

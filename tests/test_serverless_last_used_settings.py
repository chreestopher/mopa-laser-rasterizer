import ast
import math
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HANDLER = ROOT / "serverless_api" / "handler.py"


def load_cleaner():
    tree = ast.parse(HANDLER.read_text(encoding="utf-8"))
    selected = [
        node for node in tree.body
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "LAST_USED_FORM_FIELDS" for target in node.targets)
        )
        or isinstance(node, ast.FunctionDef) and node.name == "clean_last_used_form"
    ]
    namespace = {"TTL_SECONDS": 7 * 24 * 60 * 60, "time": time, "math": math}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(HANDLER), "exec"), namespace)
    return namespace["clean_last_used_form"]


def test_last_used_settings_are_allowlisted_and_expire_after_seven_days():
    clean = load_cleaner()
    current = {
        "saved_at": int(time.time()),
        "values": {
            "pixel_square_mm": ".0625",
            "image_preset": "cartoon",
            "unknown": "discard me",
        },
    }
    assert clean("last_rasterizer_form", current) == {
        "saved_at": current["saved_at"],
        "values": {"pixel_square_mm": ".0625", "image_preset": "cartoon"},
    }
    expired = {**current, "saved_at": int(time.time()) - 7 * 24 * 60 * 60 - 1}
    assert clean("last_rasterizer_form", expired) is None


def test_last_used_rasterizer_settings_retain_krasnow_cell_shape():
    clean = load_cleaner()
    current = {
        "saved_at": int(time.time()),
        "values": {
            "filter_parameters": {
                "cell_shape": "skull",
                "patch_size_mm": .4,
                "unsupported_text": "discard me",
            },
        },
    }

    assert clean("last_rasterizer_form", current)["values"]["filter_parameters"] == {
        "cell_shape": "skull",
        "patch_size_mm": .4,
    }


def test_every_member_workflow_restores_and_saves_latest_settings():
    index = (ROOT / "serverless_web" / "index.html").read_text(encoding="utf-8")
    holographic = (ROOT / "serverless_web" / "holographic.js").read_text(encoding="utf-8")
    color_lab = (ROOT / "serverless_web" / "color-lab.js").read_text(encoding="utf-8")
    template = (ROOT / "ecs" / "serverless-staging-web.yaml").read_text(encoding="utf-8")

    assert "PATCH /account/preferences" in template
    assert "restoreRasterizerForm(lastRasterizer" in index
    assert "saveLastUsed('last_rasterizer_form'" in index
    assert "restoreHolographicArtworkForm" in index
    assert "saveLastUsed('last_holographic_artwork_form'" in index
    assert 'restoreHolographicLabForm(lastUsedValues("last_holographic_lab_form"))' in holographic
    assert 'saveLastUsed("last_holographic_lab_form"' in holographic
    assert "restoreColorLabForm(lastUsedValues('last_color_lab_form'))" in color_lab
    assert "saveLastUsed('last_color_lab_form'" in color_lab


def test_member_documentation_describes_latest_settings_and_file_limit():
    docs = (ROOT / "routes" / "docs.py").read_text(encoding="utf-8")
    assert "most recently used editable settings for seven days" in docs
    assert "browsers never repopulate artwork, photographs, or Material Library file inputs" in docs

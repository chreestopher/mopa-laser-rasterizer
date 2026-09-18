import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_flipper_pair_calibration_is_available_in_both_frontends():
    legacy = (ROOT / "templates" / "holographic_etching.html").read_text(encoding="utf-8")
    serverless = (ROOT / "serverless_web" / "holographic.html").read_text(encoding="utf-8")
    script = (ROOT / "serverless_web" / "holographic.js").read_text(encoding="utf-8")
    laboratories = (ROOT / "templates" / "experimental_laboratories.html").read_text(encoding="utf-8")

    for page in (legacy, serverless):
        assert 'value="flipper_pair"' in page
        assert "Candidate A angle" in page
        assert "Candidate B angle" in page
        assert "not a two-image export" in page
    assert "grid_mode:$(\"#calibrationGridMode\").value" in script
    assert "flipper_angle_a:Number($(\"#flipperAngleA\").value)" in script
    assert "flipper_angle_b:Number($(\"#flipperAngleB\").value)" in script
    assert "Fauxlographic Flipper" in laboratories


def test_flipper_pair_grid_preserves_standard_mode_and_records_calibration():
    for relative_path in ("routes/holographic.py", "serverless_api/handler.py"):
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        ast.parse(source)
        assert 'grid_mode == "flipper_pair"' in source
        assert 'grid_mode == "flipper_pair" else' in source
        assert "flipper_pair_angles_degrees" in source
        assert "Select Fill cut mode" in source
        assert "Turn off the extra laser-setting sweep" in source
        assert "columns * rows > 29" in source

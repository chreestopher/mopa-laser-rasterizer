from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_hidden_source_rows_cannot_be_overridden_by_grid_label_styles():
    styles = (ROOT / "serverless_web" / "staging-pages.css").read_text(encoding="utf-8")
    color_lab = (ROOT / "serverless_web" / "color-lab.html").read_text(encoding="utf-8")
    holographic = (ROOT / "serverless_web" / "holographic.html").read_text(encoding="utf-8")

    assert "body.staging-prototype [hidden]{display:none!important}" in styles
    assert 'id="librarySavedRow" class="full" hidden' in color_lab
    assert 'id="calibrationLibraryRow" class="full" hidden' in holographic


def test_saved_palettes_show_their_single_material_as_read_only_text():
    rasterizer = (ROOT / "serverless_web" / "index.html").read_text(encoding="utf-8")
    holographic_page = (ROOT / "serverless_web" / "holographic.html").read_text(encoding="utf-8")
    holographic_script = (ROOT / "serverless_web" / "holographic.js").read_text(encoding="utf-8")

    assert 'id="selectedMaterialField" hidden' in rasterizer
    assert 'id="selectedMaterialName" class="selected-material-display"' in rasterizer
    assert "selectedMaterialField.hidden=!selected" in rasterizer
    assert "materialSelect.disabled=!needsMaterialSelection" in rasterizer

    assert 'id="calibrationMaterialDisplayRow" hidden' in holographic_page
    assert 'id="calibrationMaterialDisplay" class="selected-material-display"' in holographic_page
    assert '$("#calibrationMaterialRow").hidden=saved' in holographic_script
    assert '$("#calibrationMaterialDisplayRow").hidden=!saved' in holographic_script


def test_rasterizer_nested_controls_use_the_inputs_typography_in_both_modes():
    styles = (ROOT / "serverless_web" / "staging-pages.css").read_text(encoding="utf-8")
    rasterizer = (ROOT / "serverless_web" / "index.html").read_text(encoding="utf-8")

    assert "body.staging-home #job label{color:#8ee474!important" in styles
    assert "body.staging-home #job h3" in styles
    assert "body.light-machine.staging-home #job label{color:#286d24!important" in styles
    assert "body.light-machine.staging-home #job h3" in styles
    assert "body.light-machine.staging-home #job .filter-description{color:#343530!important" in styles
    assert "body.light-machine.staging-home #job input[type=checkbox]{appearance:none" in styles
    assert "background:#fff!important" in styles
    assert "input[type=checkbox]:checked::after" in styles
    assert "border:solid #20221e" in styles
    assert 'href="/staging-pages.css?v=3"' in rasterizer

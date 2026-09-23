from routes.docs import DOCS, DOC_GROUPS


def _page_text(slug):
    page = DOCS[slug]
    paragraphs = []
    for heading, items in page["sections"]:
        paragraphs.append(heading)
        for item in items:
            if isinstance(item, dict):
                paragraphs.append(item.get("html", ""))
                paragraphs.extend(str(item.get(key, "")) for key in ("before", "link_text", "after"))
            else:
                paragraphs.append(str(item))
    return " ".join(paragraphs)


def test_all_staging_features_have_public_documentation():
    catalogued = {slug for _group, slugs in DOC_GROUPS for slug in slugs}
    assert {"panel-tiling", "color-discovery-material-test-presets"} <= catalogued

    preset_text = _page_text("preset-controls")
    assert "White Is" in preset_text
    assert "Unengraved" in preset_text

    geometry_text = _page_text("geometry-styles")
    for expected in (
        "Glyph Size Source",
        "Custom uploaded glyphs",
        "Custom Uploaded Glyph",
        "Tight Pack Geometry",
        "Custom under Cell Shape",
    ):
        assert expected in geometry_text


def test_panel_tiling_guide_covers_layout_outputs_and_workbed_center():
    text = _page_text("panel-tiling")
    for expected in (
        "Horizontal and Vertical gap",
        "Set both gaps to 0",
        "Edge inset",
        "Workbed width divided by 2",
        "panel-manifest.json",
        "panel-assembly.svg",
        "no more than 100 tiles",
    ):
        assert expected in text


def test_material_test_guide_is_registered_and_linked_from_color_discovery():
    guide = DOCS["color-discovery-material-test-presets"]
    assert guide["guide"] is True
    assert guide["title"] == "Color Discovery: LightBurn Material Test Presets"
    text = _page_text("color-discovery-material-test-presets")
    assert "Laser Tools" in text
    assert "400 total cells" in text
    assert "output disabled by default" in text
    assert "color-discovery-material-test-presets" in DOCS["color-discovery"]["related"]

import json
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest
from shapely import affinity

from lib.mandala import build_mandala_exports, generate_mandala, validate_mandala_config


def sample_config():
    return {
        "project_name": "Mandala Test",
        "diameter_mm": 120,
        "workbed_width_mm": 175,
        "workbed_height_mm": 175,
        "processing_palette_name": "Workshop Processing",
        "material": "Birch",
        "cut_entry_ref": "setting:test",
        "cut_setting": {
            "description": "Cut",
            "type": "Cut",
            "settings": {"speed": "20", "minPower": "10", "maxPower": "80", "numPasses": "2"},
        },
        "layers": [
            {
                "name": "Front petals", "motif": "petal", "construction": "cutout",
                "support_mode": "automatic_bridges", "repetitions": 12, "rings": 3,
                "inner_radius_ratio": .18, "motif_scale": .72, "radial_stretch": 1,
                "tangent_stretch": 1, "twist_degrees": 18, "rotation_degrees": 0,
                "alternate_rotation": True, "mirror_alternating": False,
                "rim_width_mm": 4, "bridge_width_mm": 2, "seed": 1,
            },
            {
                "name": "Back stars", "motif": "star", "construction": "positive",
                "support_mode": "fully_connected", "repetitions": 10, "rings": 2,
                "inner_radius_ratio": .2, "motif_scale": .68, "radial_stretch": 1,
                "tangent_stretch": 1, "twist_degrees": -15, "rotation_degrees": 8,
                "alternate_rotation": True, "mirror_alternating": False,
                "rim_width_mm": 4, "bridge_width_mm": 2, "seed": 2,
            },
        ],
    }


def test_generator_preserves_exact_radial_symmetry_and_bounds():
    config, geometries = generate_mandala(sample_config())
    for layer, geometry in zip(config["layers"], geometries):
        rotated = affinity.rotate(geometry, 360 / layer["repetitions"], origin=(0, 0))
        assert geometry.symmetric_difference(rotated).area < 1e-5
        assert not geometry.is_empty
        assert max(abs(value) for value in geometry.bounds) <= config["diameter_mm"] / 2 + 1e-6


def test_connected_support_modes_export_one_physical_piece():
    config = sample_config()
    base_layer = config["layers"][1]
    for support_mode in ("automatic_bridges", "fully_connected"):
        config["layers"] = [dict(
            base_layer,
            support_mode=support_mode,
            repetitions=14,
            rings=4,
            twist_degrees=37,
            rotation_degrees=11,
        )]
        _, geometries = generate_mandala(config)
        assert geometries[0].geom_type == "Polygon"


def test_swept_wave_bridges_preserve_symmetry_and_change_geometry():
    config = sample_config()
    base_layer = dict(config["layers"][1], support_mode="fully_connected")
    config["layers"] = [base_layer]
    clean, straight = generate_mandala(config)
    config["layers"] = [dict(
        base_layer,
        support_sweep_degrees=42,
        bridge_wave_amount=1,
        bridge_wave_amplitude_mm=8,
        bridge_wave_position=.68,
    )]
    clean, waved = generate_mandala(config)
    geometry = waved[0]
    rotated = affinity.rotate(geometry, 360 / clean["layers"][0]["repetitions"], origin=(0, 0))
    assert geometry.symmetric_difference(rotated).area < 1e-5
    assert geometry.geom_type == "Polygon"
    assert geometry.symmetric_difference(straight[0]).area > 100


@pytest.mark.parametrize("sweep", [-65, -30, 30, 65])
@pytest.mark.parametrize("position", [.1, .5, .9])
def test_diagonal_wave_support_extremes_remain_one_piece(sweep, position):
    config = sample_config()
    config["layers"] = [dict(
        config["layers"][1],
        motif="leaf",
        support_mode="automatic_bridges",
        repetitions=14,
        rings=4,
        support_sweep_degrees=sweep,
        bridge_wave_amount=1,
        bridge_wave_amplitude_mm=10,
        bridge_wave_position=position,
    )]
    _, geometries = generate_mandala(config)
    assert geometries[0].geom_type == "Polygon"


def test_layer_openness_reveals_background_without_removing_connected_supports():
    config = sample_config()
    base_layer = dict(
        config["layers"][0],
        construction="cutout",
        support_mode="automatic_bridges",
        support_sweep_degrees=35,
        bridge_wave_amount=.7,
        bridge_wave_amplitude_mm=6,
    )
    config["layers"] = [dict(base_layer, layer_openness=0)]
    _, closed = generate_mandala(config)
    config["layers"] = [dict(
        base_layer,
        layer_openness=.72,
        opening_inner_ratio=.22,
        opening_rotation_degrees=11,
    )]
    clean, openwork = generate_mandala(config)
    geometry = openwork[0]
    assert geometry.geom_type == "Polygon"
    assert geometry.area < closed[0].area
    rotated = affinity.rotate(geometry, 360 / clean["layers"][0]["repetitions"], origin=(0, 0))
    assert geometry.symmetric_difference(rotated).area < 1e-5


@pytest.mark.parametrize("rim_style", ["closed", "petal", "open"])
def test_outer_edge_styles_keep_positive_connected_layers_cuttable(rim_style):
    config = sample_config()
    config["layers"] = [dict(
        config["layers"][1],
        construction="positive",
        support_mode="automatic_bridges",
        rim_style=rim_style,
        support_sweep_degrees=28,
        bridge_wave_amount=.55,
        bridge_wave_amplitude_mm=6,
    )]
    _, geometries = generate_mandala(config)
    assert geometries[0].geom_type == "Polygon"


@pytest.mark.parametrize("motif", ["petal", "leaf", "diamond", "circle", "triangle", "star", "heart"])
@pytest.mark.parametrize("support_mode", ["automatic_bridges", "fully_connected"])
def test_every_builtin_motif_honors_connected_support_modes(motif, support_mode):
    config = sample_config()
    config["layers"] = [dict(
        config["layers"][1],
        motif=motif,
        support_mode=support_mode,
        repetitions=12,
        rings=3,
        twist_degrees=23,
    )]
    _, geometries = generate_mandala(config)
    assert geometries[0].geom_type == "Polygon"


def test_rim_and_hub_truthfully_allows_loose_motifs():
    config = sample_config()
    config["layers"] = [dict(config["layers"][1], support_mode="outer_rim")]
    _, geometries = generate_mandala(config)
    assert geometries[0].geom_type == "MultiPolygon"


def test_nearly_solid_or_empty_layers_are_rejected():
    config = sample_config()
    positive_layer = config["layers"][1]
    config["layers"] = [dict(
        config["layers"][0],
        support_mode="loose",
        motif="circle",
        construction="cutout",
        repetitions=4,
        rings=1,
        motif_scale=.2,
        radial_stretch=.4,
        tangent_stretch=.4,
    )]
    with pytest.raises(ValueError, match="almost completely solid"):
        generate_mandala(config)

    config["layers"] = [dict(
        positive_layer,
        support_mode="loose",
        construction="positive",
        repetitions=4,
        rings=1,
        motif_scale=.2,
        radial_stretch=.4,
        tangent_stretch=.4,
    )]
    with pytest.raises(ValueError, match="too little material"):
        generate_mandala(config)


def test_invalid_controls_cannot_break_mandala_grammar():
    config = sample_config()
    config["layers"][0]["repetitions"] = 3
    with pytest.raises(ValueError, match="repetitions"):
        validate_mandala_config(config)
    config = sample_config()
    config["layers"] *= 7
    with pytest.raises(ValueError, match="1 to 12"):
        validate_mandala_config(config)


def test_custom_svg_motif_is_supported_and_sanitized():
    config = sample_config()
    config["layers"] = [dict(
        config["layers"][0], motif="custom",
        custom_svg={"name": "diamond.svg", "svg": '<svg viewBox="0 0 10 10"><path d="M5 0 L10 5 L5 10 L0 5 Z"/></svg>'},
    )]
    clean, geometries = generate_mandala(config)
    assert clean["layers"][0]["custom_svg"]["name"] == "diamond.svg"
    assert geometries[0].area > 0
    config["layers"][0]["custom_svg"]["svg"] = '<svg><script>alert(1)</script></svg>'
    with pytest.raises(ValueError, match="embedded or external"):
        generate_mandala(config)


def test_exports_include_combined_project_individual_layers_and_manifest(tmp_path):
    result = build_mandala_exports(tmp_path, sample_config())
    combined, assembly, archive = map(Path, result["outputs"])
    assert combined.exists() and assembly.exists() and archive.exists()
    root = ET.parse(combined).getroot()
    assert len(root.findall("./CutSetting")) == 2
    assert [node.find("./name").get("Value") for node in root.findall("./CutSetting")] == [
        "01 Front petals", "02 Back stars",
    ]
    assert all(node.get("type") == "Cut" for node in root.findall("./CutSetting"))
    assert all(node.find("./numPasses").get("Value") == "2" for node in root.findall("./CutSetting"))
    assert len(root.findall("./Shape")) == result["path_count"]
    with ZipFile(archive) as bundle:
        names = set(bundle.namelist())
        assert {"01-front-petals.svg", "01-front-petals.lbrn2", "02-back-stars.svg", "02-back-stars.lbrn2", "manifest.json", assembly.name} <= names
        manifest = json.loads(bundle.read("manifest.json"))
        assert manifest["layer_order"] == "front_to_back"
        assert [layer["index"] for layer in manifest["layers"]] == [1, 2]
        assert all(layer["path_count"] > 0 for layer in manifest["layers"])


def test_lightburn_geometry_is_centered_on_described_workbed(tmp_path):
    combined = Path(build_mandala_exports(tmp_path, sample_config())["outputs"][0])
    root = ET.parse(combined).getroot()
    points = []
    for vertex_list in root.findall(".//VertList"):
        for token in (vertex_list.text or "").split():
            if not token.startswith("V"):
                continue
            x, y = token[1:].split(",") if "," in token else (None, None)
            if x is not None:
                points.append((float(x), float(y)))
    # The writer stores one vertex per text line, so parse by line as well.
    if not points:
        for vertex_list in root.findall(".//VertList"):
            for line in (vertex_list.text or "").splitlines():
                values = line.strip().removeprefix("V").split()
                if len(values) == 2:
                    points.append(tuple(map(float, values)))
    assert points
    xs, ys = zip(*points)
    assert min(xs) == pytest.approx(27.5, abs=.02)
    assert max(xs) == pytest.approx(147.5, abs=.02)
    assert min(ys) == pytest.approx(27.5, abs=.02)
    assert max(ys) == pytest.approx(147.5, abs=.02)

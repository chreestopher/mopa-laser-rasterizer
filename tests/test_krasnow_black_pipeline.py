import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image
from shapely.geometry import LineString, box
from shapely.ops import unary_union


ROOT = Path(__file__).resolve().parents[1]
LIB_DIR = ROOT / "lib"
sys.path.insert(0, str(LIB_DIR))

# The experiment suite intentionally imports its cloned modules under these
# same top-level names. Ensure this production regression test cannot silently
# exercise the experimental copies when both suites are collected together.
for module_name in list(sys.modules):
    if module_name == "vector_processing" or module_name == "abstract_filters" \
            or module_name.startswith("abstract_filters."):
        del sys.modules[module_name]

import vector_processing


def test_krasnow_uses_source_faithful_vector_defaults():
    krasnow = vector_processing.ABSTRACT_FILTER_MODULES["krasnow_grating"]
    assert krasnow.VECTOR_DEFAULTS == {
        "min_island_area": 0,
        "simplification_factor": 0.0,
        "smoothing_radius": 0.001,
    }


def test_krasnow_accepts_fauxlographic_and_classic_holographic_setting_names():
    class MaterialLibrary:
        def __init__(self, setting):
            self.setting = setting
            self.layers = []

        def parse_material_library(self, _path):
            return [self.setting]

        def add_layer(self, layer):
            self.layers.append(layer)

    for setting_name in ("Fauxlographic", "Holographic"):
        setting = SimpleNamespace(
            materialName="Stainless",
            entryDesc=setting_name,
            name=setting_name,
            frequency=120000,
        )
        library = MaterialLibrary(setting)
        matched, required = vector_processing.parse_material_settings(
            library,
            "unused.clb",
            [],
            {"#000000": (0, 0, "Black")},
            material_name="Stainless",
            required_setting_names=["fauxlographic"],
            required_setting_aliases={"fauxlographic": ("holographic",)},
            return_setting_layers=True,
        )

        assert matched == {}
        assert required == {"fauxlographic": 1}
        assert library.layers == [setting]


def test_material_swatch_matching_ignores_stale_cut_setting_names():
    class MaterialLibrary:
        def __init__(self, settings):
            self.settings = settings
            self.layers = []

        def parse_material_library(self, _path):
            return self.settings

        def add_layer(self, layer):
            self.layers.append(layer)

    teal = SimpleNamespace(
        materialName="Stainless-2", entryDesc="Teal", name="Teal",
        frequency=120000, minPower=10, maxPower=20, speed=1000,
        QPulseWidth=100,
    )
    light_blue_with_stale_name = SimpleNamespace(
        materialName="Stainless-2", entryDesc="Light-Blue", name="Teal",
        frequency=120000, minPower=10, maxPower=20, speed=1000,
        QPulseWidth=100,
    )
    library = MaterialLibrary([teal, light_blue_with_stale_name])

    matched = vector_processing.parse_material_settings(
        library,
        "unused.clb",
        ["Teal"],
        {"#004754": (0, 27, "Teal")},
        material_name="Stainless-2",
    )

    assert matched == {"#004754": (0, 27, "Teal")}
    assert library.layers == [teal]
    assert light_blue_with_stale_name.name == "Teal"


def test_material_with_no_matching_swatch_descriptions_reports_actionable_error():
    class MaterialLibrary:
        def __init__(self):
            self.layers = []

        def parse_material_library(self, _path):
            return [
                SimpleNamespace(materialName="Stainless", entryDesc="Magenta 210mm"),
                SimpleNamespace(materialName="Stainless", entryDesc="Dark Blue on Stainless"),
            ]

        def add_layer(self, layer):
            self.layers.append(layer)

    library = MaterialLibrary()
    with pytest.raises(ValueError, match="No colors in Material Library material 'stainless' matched.*Rasterizer swatch names") as error:
        vector_processing.parse_material_settings(
            library,
            "unused.clb",
            ["Black", "Blue"],
            {"#000000": (0, 0, "Black"), "#0000FF": (240, 1, "Blue")},
            material_name="stainless",
        )

    assert "LightBurn entry descriptions" in str(error.value)
    assert library.layers == []


def test_required_setting_matching_ignores_cut_setting_name():
    class MaterialLibrary:
        def __init__(self, setting):
            self.setting = setting
            self.layers = []

        def parse_material_library(self, _path):
            return [self.setting]

        def add_layer(self, layer):
            self.layers.append(layer)

    setting = SimpleNamespace(
        materialName="Stainless-2",
        entryDesc="Light-Blue",
        name="Fauxlographic",
        frequency=120000,
    )
    library = MaterialLibrary(setting)

    with pytest.raises(ValueError, match="missing the cut setting required for this fauxlogram job") as error:
        vector_processing.parse_material_settings(
            library,
            "unused.clb",
            [],
            {"#000000": (0, 0, "Black")},
            material_name="Stainless-2",
            required_setting_names=["fauxlographic"],
            return_setting_layers=True,
        )

    assert "Description is 'fauxlographic'" in str(error.value)
    assert "'holographic' also works" in str(error.value)
    assert "Cut mode" in str(error.value)
    assert library.layers == []


def test_krasnow_output_layers_use_parent_recipe_not_offset_sublayer():
    krasnow = vector_processing.ABSTRACT_FILTER_MODULES["krasnow_grating"]
    child = SimpleNamespace(
        speed=500,
        frequency=60000,
        QPulseWidth=None,
        subLayers=[],
    )
    parent = SimpleNamespace(
        index=30,
        name="Holographic",
        type="Offset",
        speed=1000,
        frequency=120000,
        QPulseWidth=120,
        materialName="Stainless-2",
        entryDesc="holographic",
        subLayers=[child],
    )
    project = SimpleNamespace(_layers=[parent])

    krasnow.configure_output_layers(
        project,
        {"#0000FF": (240, 1, "Blue")},
        {"_setting_layer_id": 30, "speed_spread": 1},
    )

    assert len(project._layers) == 1
    output = project._layers[0]
    assert output.index == 1
    assert output.type == "Cut"
    assert output.frequency == 120000
    assert output.QPulseWidth == 120
    assert output.speed == 1000
    assert output.subLayers == []


def test_krasnow_native_fill_automatically_balances_available_layer_slots():
    krasnow = vector_processing.ABSTRACT_FILTER_MODULES["krasnow_grating"]

    assert krasnow._automatic_fill_dimensions(6) == (3, 2)
    assert krasnow._automatic_fill_dimensions(21) == (7, 3)
    assert krasnow._automatic_fill_dimensions(29) == (7, 4)
    assert krasnow._automatic_fill_dimensions(30) == (7, 4)


def test_krasnow_native_fill_configures_scan_layers_from_anchor_recipe():
    krasnow = vector_processing.ABSTRACT_FILTER_MODULES["krasnow_grating"]
    anchor = SimpleNamespace(
        index=30,
        name="Fauxlographic",
        type="Cut",
        speed=300,
        frequency=300000,
        QPulseWidth=5,
        minPower=18,
        maxPower=20,
        materialName="Stainless",
        entryDesc="Fauxlographic",
        subLayers=[SimpleNamespace(speed=999)],
    )
    target_colors = {
        color: (0, index, f"Carrier {index}")
        for index, color in enumerate(
            ("#0000FF", "#FF0000", "#00E000", "#D0D000", "#FF8000", "#00E0E0"),
            1,
        )
    }
    project = SimpleNamespace(_layers=[anchor])

    krasnow.configure_output_layers(
        project,
        target_colors,
        {
            "_setting_layer_id": 30,
            "grating_render_mode": "fill",
            "line_spacing_mm": .075,
            "angle_min": -90,
            "angle_max": 90,
            "speed_spread": 1,
        },
    )

    assert len(project._layers) == 6
    assert all(layer.type == "Scan" for layer in project._layers)
    assert all(layer.interval == .075 for layer in project._layers)
    assert all(layer.scanOpt == "individual" for layer in project._layers)
    assert all(layer.floodFill is False for layer in project._layers)
    assert all(layer.subLayers == [] for layer in project._layers)
    assert {layer.frequency for layer in project._layers} == {300000}
    assert {layer.QPulseWidth for layer in project._layers} == {5}
    # Six slots become three pitch carriers with two angle bins each.
    assert [layer.speed for layer in project._layers] == [165, 165, 315, 315, 465, 465]
    assert len({layer.angle for layer in project._layers}) == 2


def test_krasnow_native_fill_emits_closed_cell_geometry_within_source():
    krasnow = vector_processing.ABSTRACT_FILTER_MODULES["krasnow_grating"]
    source = box(.1, .1, 1.9, 1.9)
    target_colors = {
        "#0000FF": (240, 1, "Blue"),
        "#FF0000": (1, 2, "Red"),
        "#00E000": (120, 3, "Green"),
        "#D0D000": (60, 4, "Yellow"),
    }
    angle_image = Image.fromarray(np.array([
        [0, 0, 255, 255],
        [0, 0, 255, 255],
        [0, 0, 255, 255],
        [0, 0, 255, 255],
    ], dtype=np.uint8), mode="L")

    remapped = krasnow.remap_layers(
        {"#0000FF": source},
        target_colors,
        {
            "_canvas_bounds": (0, 0, 2, 2),
            "_scale_factor": 1,
            "_setting_layer_id": 30,
            "_angle_image": angle_image,
            "grating_render_mode": "fill",
            "patch_size_mm": .5,
            "angle_min": -90,
            "angle_max": 90,
        },
    )

    assert remapped
    assert len(remapped) <= 4
    for geometry in remapped.values():
        assert geometry.geom_type in {"Polygon", "MultiPolygon"}
        assert geometry.difference(source).area < 1e-8


def test_krasnow_native_fill_requires_material_library_backing():
    krasnow = vector_processing.ABSTRACT_FILTER_MODULES["krasnow_grating"]
    with pytest.raises(ValueError, match="requires a Material Library-backed job"):
        krasnow.remap_layers(
            {"#0000FF": box(0, 0, 1, 1)},
            {"#0000FF": (240, 1, "Blue")},
            {
                "_canvas_bounds": (0, 0, 1, 1),
                "grating_render_mode": "fill",
            },
        )


def test_krasnow_unpreserved_black_layer_uses_holographic_parent_recipe():
    krasnow = vector_processing.ABSTRACT_FILTER_MODULES["krasnow_grating"]
    original_black = SimpleNamespace(
        index=0,
        name="Black",
        type="Cut",
        speed=250,
        frequency=30000,
        QPulseWidth=200,
        minPower=18,
        maxPower=20,
        subLayers=[],
    )
    holographic = SimpleNamespace(
        index=30,
        name="Holographic",
        type="Cut",
        speed=1000,
        frequency=120000,
        QPulseWidth=120,
        minPower=42,
        maxPower=45,
        materialName="Stainless-2",
        entryDesc="holographic",
        subLayers=[],
    )
    project = SimpleNamespace(_layers=[original_black, holographic])

    krasnow.configure_output_layers(
        project,
        {"#000000": (0, 0, "Black")},
        {"_setting_layer_id": 30, "preserve_black": 0},
    )

    assert len(project._layers) == 1
    output = project._layers[0]
    assert output is not original_black
    assert output.index == 0
    assert output.name == "Black"
    assert output.type == "Cut"
    assert output.frequency == 120000
    assert output.QPulseWidth == 120
    assert output.minPower == 42
    assert output.maxPower == 45
    assert output.subLayers == []


def test_krasnow_cell_shape_defaults_to_legacy_square():
    krasnow = vector_processing.ABSTRACT_FILTER_MODULES["krasnow_grating"]
    assert krasnow.DEFAULTS["cell_shape"] == "square"
    assert krasnow._cell_shape({}) == "square"
    assert krasnow._cell_shape({"cell_shape": "unsupported"}) == "square"


def test_krasnow_non_square_cells_tessellate_without_gaps_or_overlaps():
    krasnow = vector_processing.ABSTRACT_FILTER_MODULES["krasnow_grating"]
    bounds = (0, 0, 8, 6)
    canvas = box(*bounds)

    for cell_shape in ("hexagon", "triangle", "diamond", "puzzle_piece"):
        cells = krasnow._tessellated_cells(bounds, 1, cell_shape)
        clipped = [polygon.intersection(canvas) for _, polygon in cells]
        covered = unary_union(clipped)

        assert canvas.symmetric_difference(covered).area < 1e-8
        assert sum(polygon.area for polygon in clipped) - covered.area < 1e-8


def test_krasnow_non_square_cell_generation_is_deterministic():
    krasnow = vector_processing.ABSTRACT_FILTER_MODULES["krasnow_grating"]

    for cell_shape in ("hexagon", "triangle", "diamond"):
        first = krasnow._tessellated_cells((0, 0, 4, 3), .4, cell_shape)
        second = krasnow._tessellated_cells((0, 0, 4, 3), .4, cell_shape)
        assert [(key, polygon.wkb) for key, polygon in first] == [
            (key, polygon.wkb) for key, polygon in second
        ]


def test_krasnow_skull_cells_have_deliberate_external_and_internal_gaps():
    krasnow = vector_processing.ABSTRACT_FILTER_MODULES["krasnow_grating"]
    bounds = (0, 0, 4, 3)
    canvas = box(*bounds)
    cells = krasnow._tessellated_cells(bounds, 1, "skull")
    clipped = [polygon.intersection(canvas) for _, polygon in cells]
    covered = unary_union(clipped)

    assert covered.area < canvas.area * .75
    assert all(polygon.is_valid for polygon in clipped)
    assert any(len(polygon.interiors) >= 3 for _, polygon in cells)


def test_krasnow_skull_cell_generation_is_deterministic():
    krasnow = vector_processing.ABSTRACT_FILTER_MODULES["krasnow_grating"]
    first = krasnow._tessellated_cells((0, 0, 4, 3), .8, "skull")
    second = krasnow._tessellated_cells((0, 0, 4, 3), .8, "skull")
    assert [(key, polygon.wkb) for key, polygon in first] == [
        (key, polygon.wkb) for key, polygon in second
    ]


def test_krasnow_skull_rows_are_staggered_and_do_not_overlap():
    krasnow = vector_processing.ABSTRACT_FILTER_MODULES["krasnow_grating"]
    cells = dict(krasnow._tessellated_cells((0, 0, 4, 4), 1, "skull"))
    first = cells[(0, 0)]
    staggered = cells[(1, 0)]

    assert abs(staggered.centroid.x - first.centroid.x - .5) < 1e-9
    assert abs(staggered.centroid.y - first.centroid.y - .8) < 1e-9
    assert first.intersection(staggered).area < 1e-12
    assert first.distance(staggered) > 0


def test_krasnow_fun_icon_cells_are_valid_deterministic_and_nonoverlapping():
    krasnow = vector_processing.ABSTRACT_FILTER_MODULES["krasnow_grating"]
    shapes = (
        "heart", "space_invader", "ghost", "bat", "alien_head",
        "paw_print", "fish_scale",
    )

    for cell_shape in shapes:
        first = krasnow._tessellated_cells((0, 0, 4, 4), 1, cell_shape)
        second = krasnow._tessellated_cells((0, 0, 4, 4), 1, cell_shape)
        cells = dict(first)
        same_row = cells[(0, 0)]
        next_column = cells[(0, 1)]
        next_row = cells[(1, 0)]

        assert [(key, polygon.wkb) for key, polygon in first] == [
            (key, polygon.wkb) for key, polygon in second
        ]
        assert all(polygon.is_valid for _, polygon in first)
        assert same_row.intersection(next_column).area < 1e-12
        assert same_row.intersection(next_row).area < 1e-12


def test_krasnow_explicit_square_matches_implicit_legacy_default():
    krasnow = vector_processing.ABSTRACT_FILTER_MODULES["krasnow_grating"]
    processed_layers = {"#0000FF": box(0, 0, 2, 2)}
    target_colors = {"#0000FF": (240, 1, "Blue")}
    settings = {
        "_canvas_bounds": (0, 0, 2, 2),
        "_scale_factor": 1,
        "patch_size_mm": 1,
        "line_spacing_mm": .25,
        "angle_min": 0,
        "angle_max": 0,
    }

    implicit = krasnow.remap_layers(processed_layers, target_colors, settings)
    explicit = krasnow.remap_layers(
        processed_layers,
        target_colors,
        {**settings, "cell_shape": "square"},
    )

    assert implicit.keys() == explicit.keys()
    assert all(implicit[key].wkb == explicit[key].wkb for key in implicit)


def test_krasnow_each_cell_shape_stays_inside_source_geometry():
    krasnow = vector_processing.ABSTRACT_FILTER_MODULES["krasnow_grating"]
    source = box(.2, .15, 2.7, 2.4)
    target_colors = {"#0000FF": (240, 1, "Blue")}

    for cell_shape in (
        "square", "hexagon", "triangle", "diamond", "skull", "heart",
        "space_invader", "ghost", "bat", "alien_head", "paw_print",
        "fish_scale", "puzzle_piece",
    ):
        remapped = krasnow.remap_layers(
            {"#0000FF": source},
            target_colors,
            {
                "_canvas_bounds": (0, 0, 3, 3),
                "_scale_factor": 1,
                "cell_shape": cell_shape,
                "patch_size_mm": .6,
                "line_spacing_mm": .15,
                "angle_min": 25,
                "angle_max": 25,
            },
        )
        assert remapped["#0000FF"].difference(source).length < 1e-8


def test_serverless_krasnow_form_exposes_tessellating_cell_shapes():
    page = (ROOT / "serverless_web" / "index.html").read_text(encoding="utf-8")
    assert "selects:[['cell_shape','square'" in page
    assert "['hexagon','Hexagon']" in page
    assert "['triangle','Triangle']" in page
    assert "['diamond','Diamond / Rhombus']" in page
    assert "['skull','Skull']" in page
    assert "['heart','Heart']" in page
    assert "['space_invader','Space Invader']" in page
    assert "['ghost','Ghost']" in page
    assert "['bat','Bat']" in page
    assert "['alien_head','Alien Head']" in page
    assert "['paw_print','Paw Print']" in page
    assert "['fish_scale','Fish Scale']" in page
    assert "['puzzle_piece','Puzzle Piece']" in page


def test_krasnow_equal_hue_spacing_limits_preserve_legacy_spacing():
    krasnow = vector_processing.ABSTRACT_FILTER_MODULES["krasnow_grating"]
    settings = {
        "line_spacing_mm": 0.2,
        "hue_line_spacing_minimum_mm": 0.06,
        "hue_line_spacing_maximum_mm": 0.06,
    }

    assert krasnow._line_spacing_for_color("#FF0000", settings, 2) == 0.03
    assert krasnow._line_spacing_for_color("#0000FF", settings, 2) == 0.03


def test_krasnow_hue_spacing_follows_wavelength_order():
    krasnow = vector_processing.ABSTRACT_FILTER_MODULES["krasnow_grating"]
    settings = {
        "hue_line_spacing_minimum_mm": 0.04,
        "hue_line_spacing_maximum_mm": 0.08,
    }

    violet = krasnow._line_spacing_for_color("#8000FF", settings, 1)
    blue = krasnow._line_spacing_for_color("#0000FF", settings, 1)
    green = krasnow._line_spacing_for_color("#00FF00", settings, 1)
    red = krasnow._line_spacing_for_color("#FF0000", settings, 1)

    assert violet < blue < green < red
    assert red == 0.08


def test_krasnow_neutral_colors_use_general_line_spacing():
    krasnow = vector_processing.ABSTRACT_FILTER_MODULES["krasnow_grating"]
    settings = {
        "line_spacing_mm": 0.125,
        "hue_line_spacing_minimum_mm": 0.04,
        "hue_line_spacing_maximum_mm": 0.08,
        "saturation_cutoff": 0.2,
    }

    assert krasnow._line_spacing_for_color("#CCCCCC", settings, 5) == 0.025


def test_krasnow_does_not_build_gratings_from_black_geometry():
    krasnow = vector_processing.ABSTRACT_FILTER_MODULES["krasnow_grating"]
    remapped = krasnow.remap_layers(
        processed_layers={"#000000": box(0, 0, 2, 2)},
        target_colors={
            "#000000": (0, 0, "Black"),
            "#0000FF": (240, 1, "Blue"),
            "#FF0000": (0, 2, "Red"),
        },
        settings={
            "_canvas_bounds": (0, 0, 2, 2),
            "_scale_factor": 1,
            "patch_size_mm": 1,
            "line_spacing_mm": 0.25,
            "angle_min": 0,
            "angle_max": 0,
        },
    )

    assert remapped == {}


def test_krasnow_builds_gratings_from_black_when_preserve_black_is_off():
    krasnow = vector_processing.ABSTRACT_FILTER_MODULES["krasnow_grating"]
    remapped = krasnow.remap_layers(
        processed_layers={"#000000": box(0, 0, 2, 2)},
        target_colors={"#000000": (0, 0, "Black")},
        settings={
            "preserve_black": 0,
            "_canvas_bounds": (0, 0, 2, 2),
            "_scale_factor": 1,
            "patch_size_mm": 1,
            "line_spacing_mm": 0.25,
            "angle_min": 0,
            "angle_max": 0,
        },
    )

    assert set(remapped) == {"#000000"}
    assert not remapped["#000000"].is_empty


def test_krasnow_cross_layer_mapping_reports_internal_progress():
    krasnow = vector_processing.ABSTRACT_FILTER_MODULES["krasnow_grating"]
    messages = []

    remapped = krasnow.remap_layers(
        processed_layers={"#0000FF": box(0, 0, 2, 2)},
        target_colors={
            "#000000": (0, 0, "Black"),
            "#0000FF": (240, 1, "Blue"),
        },
        settings={
            "_canvas_bounds": (0, 0, 2, 2),
            "_scale_factor": 1,
            "_progress_logger": messages.append,
            "patch_size_mm": 1,
            "line_spacing_mm": 0.25,
            "angle_min": 0,
            "angle_max": 0,
        },
    )

    assert remapped
    assert any("[Krasnow mapping 1/3] DONE" in message for message in messages)
    assert any("[Krasnow mapping 2/3] PROGRESS" in message for message in messages)
    assert any("[Krasnow mapping 3/3] Carrier 1/1 START" in message for message in messages)
    assert any("[Krasnow mapping 3/3] DONE" in message for message in messages)


def test_krasnow_prunes_empty_space_between_disconnected_components():
    krasnow = vector_processing.ABSTRACT_FILTER_MODULES["krasnow_grating"]
    messages = []
    components = [box(0, 0, 1, 1), box(9, 9, 10, 10)]
    settings = {
        "_canvas_bounds": (0, 0, 10, 10),
        "_scale_factor": 1,
        "_progress_logger": messages.append,
        "patch_size_mm": 1,
        "line_spacing_mm": 0.25,
        "angle_min": 0,
        "angle_max": 0,
    }
    target_colors = {"#0000FF": (240, 1, "Blue")}

    remapped = krasnow.remap_layers(
        processed_layers={"#0000FF": unary_union(components)},
        target_colors=target_colors,
        settings=settings,
    )
    independently_remapped = [
        krasnow.remap_layers(
            processed_layers={"#0000FF": component},
            target_colors=target_colors,
            settings={key: value for key, value in settings.items() if key != "_progress_logger"},
        )["#0000FF"]
        for component in components
    ]

    assert any("planned 2 candidate patches" in message for message in messages)
    assert remapped["#0000FF"].equals(unary_union(independently_remapped))


def test_krasnow_black_mask_owns_its_footprint_exclusively():
    blue = box(0, 0, 2, 1).boundary.union(
        LineString([(0, .5), (2, .5)])
    )
    old_black = box(10, 10, 11, 11)
    source = Image.new("RGB", (2, 1))
    source.putdata([(0, 0, 0), (255, 255, 255)])

    replaced = vector_processing.replace_krasnow_black_layer(
        {"#0000FF": blue, "#000000": old_black},
        "#000000",
        source,
        reserved_black_mask=np.array([[True, False]], dtype=bool),
    )

    assert replaced["#000000"].equals(box(0, 0, 1, 1))
    assert replaced["#0000FF"].intersection(replaced["#000000"]).length <= 1e-9
    assert replaced["#0000FF"].intersection(box(1, 0, 2, 1)).length > 0


def test_krasnow_preserve_black_uses_only_pre_reserved_black_pixels():
    grating = box(1, 0, 2, 1).boundary
    source = Image.new("RGB", (3, 1))
    source.putdata([(0, 0, 0), (0, 72, 84), (255, 255, 255)])

    replaced = vector_processing.replace_krasnow_black_layer(
        {"#0000FF": grating},
        "#000000",
        source,
        reserved_black_mask=np.array([[True, False, False]], dtype=bool),
    )

    assert replaced["#000000"].equals(box(0, 0, 1, 1))
    assert replaced["#0000FF"].intersection(replaced["#000000"]).length <= 1e-9
    assert replaced["#0000FF"].intersection(box(1, 0, 2, 1)).length > 0


def test_serverless_krasnow_form_exposes_preserve_black_checked():
    page = (ROOT / "serverless_web" / "index.html").read_text(encoding="utf-8")
    assert "toggles:[['preserve_black',true]]" in page
    assert "favor_black" not in page


def test_krasnow_preserve_black_rejects_a_misaligned_reserved_mask():
    source = Image.new("RGB", (3, 1))

    with np.testing.assert_raises_regex(ValueError, "does not match"):
        vector_processing.replace_krasnow_black_layer(
            {},
            "#000000",
            source,
            reserved_black_mask=np.zeros((2, 3), dtype=bool),
        )


def test_krasnow_black_cutoff_is_strictly_below_lightburn_teal():
    source = Image.new("RGB", (3, 1))
    source.putdata([(0, 70, 84), (0, 71, 84), (0, 72, 84)])

    mask = vector_processing.source_black_cutoff_mask(source)

    assert mask.tolist() == [[True, False, False]]


def test_nonblack_krasnow_palette_cannot_introduce_black(tmp_path):
    source = Image.new("RGB", (3, 1))
    source.putdata([(1, 1, 1), (5, 0, 0), (0, 0, 5)])
    source_path = tmp_path / "dark-source.png"
    source.save(source_path)

    quantized = vector_processing.prepare_raster_image(
        raster_image_path=source_path,
        new_height=0,
        new_width=3,
        quantize_colors=2,
        target_colors={"#A00000": (), "#0000A0": ()},
        prevent_palette_black=True,
    )

    pixels = {tuple(pixel) for pixel in np.asarray(quantized).reshape(-1, 3)}
    assert (0, 0, 0) not in pixels
    assert pixels <= {(160, 0, 0), (0, 0, 160)}

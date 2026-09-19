import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
LIB_DIR = ROOT / "lib"
sys.path.insert(0, str(LIB_DIR))

pytest.importorskip("potrace")
pytest.importorskip("shapely")

import Material_Library
import vector_processing


def test_one_selected_swatch_is_not_expanded_to_the_whole_palette():
    targets = {
        "#FF0000": (1, 2, "Red"),
    }

    assert Material_Library.selected_material_color_names("Red", targets) == ["Red"]


def test_init_lightburn_does_not_restore_unassigned_black_or_light_gray():
    targets, _project, _module = vector_processing.init_lightburn("Red")

    assert set(targets) == {"#FF0000"}


def test_unassigned_black_setting_is_not_loaded_into_lightburn():
    targets, project, _module = vector_processing.init_lightburn("Red")
    black = SimpleNamespace(
        materialName="Stainless-2", entryDesc="Black", name="",
        frequency=100000, minPower=10, maxPower=20, speed=1000,
        QPulseWidth=100,
    )
    red = SimpleNamespace(
        materialName="Stainless-2", entryDesc="Red", name="",
        frequency=100000, minPower=10, maxPower=20, speed=1000,
        QPulseWidth=100,
    )
    project.parse_material_library = lambda _path: [black, red]

    matched = vector_processing.parse_material_settings(
        project,
        "unused.clb",
        ["Red"],
        targets,
        material_name="Stainless-2",
    )

    assert matched == {"#FF0000": (1, 2, "Red")}
    assert project._layers == [red]
    assert all(layer.index != 0 for layer in project._layers)

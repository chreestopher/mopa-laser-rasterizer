import sys
from collections import defaultdict
from pathlib import Path

from PIL import Image
from shapely.geometry import MultiPolygon, Polygon, box


EXPERIMENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXPERIMENT_DIR))

import vector_processing as experiment


def test_experiment_is_configured_for_spatially_grouped_punchthrough():
    assert experiment.NO_SYNTHETIC_BLACK_CANVAS is False
    assert experiment.SPATIALLY_GROUP_PUNCHTHROUGH is True
    assert experiment.CONSTRAIN_NONBLACK_DEFAULT is False


def test_krasnow_vector_defaults_preserve_source_outlines():
    krasnow = experiment.ABSTRACT_FILTER_MODULES["krasnow_grating"]
    assert krasnow.VECTOR_DEFAULTS == {
        "min_island_area": 0,
        "simplification_factor": 0.0,
        "smoothing_radius": 0.001,
    }


def test_krasnow_remaps_black_through_grating_carriers():
    krasnow = experiment.ABSTRACT_FILTER_MODULES["krasnow_grating"]
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

    assert "#000000" not in remapped
    assert remapped
    assert all(
        geometry.geom_type in {"LineString", "MultiLineString"}
        for geometry in remapped.values()
    )


def test_holographic_lab_black_mask_selects_adaptive_dark_pixels():
    source = Image.new("RGB", (4, 1))
    source.putdata([
        (0, 0, 0),
        (16, 16, 16),
        (240, 240, 240),
        (255, 255, 255),
    ])

    mask = experiment.holographic_lab_black_mask(source)

    assert mask.tolist() == [[True, True, False, False]]


def test_krasnow_black_replacement_does_not_change_carrier_layers():
    blue = box(0, 0, 1, 1).boundary
    red = box(1, 0, 2, 1).boundary
    previous_black = box(10, 10, 11, 11)
    layers = {
        "#0000FF": blue,
        "#FF0000": red,
        "#000000": previous_black,
    }
    source = Image.new("RGB", (2, 1))
    source.putdata([(0, 0, 0), (255, 255, 255)])

    replaced = experiment.replace_krasnow_black_layer(
        layers,
        "#000000",
        source,
    )

    assert replaced["#0000FF"] is blue
    assert replaced["#FF0000"] is red
    assert replaced["#000000"].equals(box(0, 0, 1, 1))
    assert layers["#000000"] is previous_black


def test_only_source_pixels_below_teal_are_restored_as_black():
    source = Image.new("RGB", (3, 1))
    source.putdata([(0, 0, 0), (0, 71, 84), (255, 255, 255)])
    quantized_without_black = Image.new("RGB", (3, 1), (160, 0, 0))

    restored = experiment.restore_reserved_black(
        quantized_without_black,
        experiment.source_black_cutoff_mask(source),
    )

    assert list(restored.getdata()) == [
        (0, 0, 0),
        (160, 0, 0),
        (160, 0, 0),
    ]


def test_source_black_cutoff_uses_lightburn_teal_as_strict_boundary():
    source = Image.new("RGB", (3, 1))
    source.putdata([(0, 70, 84), (0, 71, 84), (0, 72, 84)])

    mask = experiment.source_black_cutoff_mask(source)

    assert mask.tolist() == [[True, False, False]]


def test_source_black_cutoff_mask_resizes_without_interpolation(tmp_path):
    source = Image.new("RGB", (4, 1))
    source.putdata([(0, 0, 0), (0, 255, 0), (255, 255, 255), (0, 255, 255)])
    source_path = tmp_path / "source.png"
    source.save(source_path)

    mask = experiment.load_resized_source_black_cutoff_mask(source_path, (8, 1))

    assert mask.tolist() == [[True, True, False, False, False, False, False, False]]


def test_nonblack_palette_padding_cannot_introduce_black(tmp_path):
    source = Image.new("RGB", (3, 1))
    source.putdata([(1, 1, 1), (5, 0, 0), (0, 0, 5)])
    source_path = tmp_path / "dark-source.png"
    source.save(source_path)

    quantized = experiment.prepare_raster_image(
        raster_image_path=source_path,
        new_height=0,
        new_width=3,
        quantize_colors=2,
        target_colors={
            "#A00000": (359, 10, "Dark-Red"),
            "#0000A0": (240, 9, "Dark-Blue"),
        },
    )

    assert (0, 0, 0) not in list(quantized.getdata())
    assert set(quantized.getdata()) <= {(160, 0, 0), (0, 0, 160)}


def test_source_black_is_classified_as_real_black_geometry():
    image = Image.new("RGB", (2, 1))
    image.putdata([(0, 0, 0), (255, 0, 0)])
    target_colors = {
        "#000000": (0, 0, "Black"),
        "#FF0000": (0, 2, "Red"),
    }

    layers = experiment.classify_raster_pixels(
        img=image,
        target_colors=target_colors,
        black_hex="#000000",
        ignore_background_hex="#FFFFFF",
        include_black=True,
    )

    assert isinstance(layers, defaultdict)
    assert len(layers["#000000"]) == 1
    assert layers["#000000"][0].bounds == (0.0, 0.0, 1.0, 1.0)
    assert len(layers["#FF0000"]) == 1
    assert layers["#FF0000"][0].bounds == (1.0, 0.0, 2.0, 1.0)


def test_contained_colors_group_together_but_black_stays_black_only():
    outer_blue = Polygon(
        [(0, 0), (10, 0), (10, 10), (0, 10)],
        holes=[[(2, 2), (8, 2), (8, 8), (2, 8)]],
    )
    inner_blue = box(3, 3, 4, 4)
    inner_black = box(6, 6, 7, 7)

    groups = experiment.build_spatial_export_groups(
        {
            "#0000FF": MultiPolygon([outer_blue, inner_blue]),
            "#000000": inner_black,
        },
        black_hex="#000000",
    )

    matching = [
        group for group in groups
        if any(record["geometry"].equals(outer_blue) for record in group)
    ]
    assert len(matching) == 1
    grouped_records = matching[0]
    assert any(record["geometry"].equals(inner_blue) for record in grouped_records)
    assert not any(record["color"] == "#000000" for record in grouped_records)
    black_groups = [
        group for group in groups
        if group and all(record["color"] == "#000000" for record in group)
    ]
    assert len(black_groups) == 1
    assert any(record["geometry"].equals(inner_black) for record in black_groups[0])

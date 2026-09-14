import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image
from shapely.geometry import GeometryCollection, LineString, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union


ROOT = Path(__file__).resolve().parents[1]
LIB_DIR = ROOT / "lib"
sys.path.insert(0, str(LIB_DIR))

import vector_processing
import lightburn


def test_black_run_rectangles_preserve_sparse_outline_exactly():
    black_pixels = [
        box(x, y, x + 1, y + 1)
        for y in range(3)
        for x in range(3)
        if (x, y) != (1, 1)
    ]

    rectangles = vector_processing._raster_boxes_to_rectangles(black_pixels)

    assert sum(item.area for item in rectangles) == 8
    assert unary_union(rectangles).equals(unary_union(black_pixels))
    assert all(not item.interiors for item in rectangles)


def test_parallel_source_black_components_are_byte_identical_to_serial():
    black_pixels = [
        box(x, y, x + 1, y + 1)
        for y in range(6)
        for x in range(8)
        if x in (0, 3, 7) or y in (0, 5)
    ]
    processed_layers = {
        "#FF0000": box(2.75, 1, 4.25, 5),
        "#00E000": box(6.75, 2, 8, 4),
    }

    serial = vector_processing.build_source_black_component_layer(
        black_pixel_boxes=black_pixels,
        processed_layers=processed_layers,
        black_hex="#000000",
        worker_count=1,
    )
    parallel = vector_processing.build_source_black_component_layer(
        black_pixel_boxes=black_pixels,
        processed_layers=processed_layers,
        black_hex="#000000",
        worker_count=2,
    )

    assert parallel.wkb == serial.wkb
    for geometry in processed_layers.values():
        assert parallel.intersection(geometry).area <= 1e-6


def test_precompressed_source_black_is_byte_identical_to_raw_pixels():
    black_pixels = [
        box(x, y, x + 1, y + 1)
        for y in range(8)
        for x in range(10)
        if x in (0, 1, 5, 9) or y in (0, 7)
    ]
    processed_layers = {"#FF0000": box(4.5, 2, 6.5, 7)}
    rectangles = vector_processing._raster_boxes_to_rectangles(black_pixels)

    raw = vector_processing.build_source_black_component_layer(
        black_pixel_boxes=black_pixels,
        processed_layers=processed_layers,
        black_hex="#000000",
        worker_count=1,
    )
    precompressed = vector_processing.build_source_black_component_layer(
        black_pixel_boxes=(),
        black_rectangles=rectangles,
        processed_layers=processed_layers,
        black_hex="#000000",
        worker_count=1,
    )

    assert precompressed.wkb == raw.wkb


def test_source_black_progress_logs_coarse_batches_without_changing_output(monkeypatch):
    black_pixels = [box(x * 2, 0, x * 2 + 1, 1) for x in range(12)]
    messages = []
    monkeypatch.setattr(vector_processing, "SOURCE_BLACK_PROGRESS_MIN_COMPONENTS", 1)
    monkeypatch.setattr(vector_processing, "printLogMessage", messages.append)

    result = vector_processing.build_source_black_component_layer(
        black_pixel_boxes=black_pixels,
        processed_layers={},
        black_hex="#000000",
        worker_count=2,
    )

    starts = [message for message in messages if " batch " in message and "START:" in message]
    completions = [message for message in messages if " batch " in message and "DONE:" in message]
    assert len(starts) == vector_processing.SOURCE_BLACK_PROGRESS_BATCHES
    assert len(completions) == vector_processing.SOURCE_BLACK_PROGRESS_BATCHES
    assert "processed 12/12 component(s)" in completions[-1]
    assert unary_union(result).equals(unary_union(black_pixels))


@pytest.mark.parametrize(
    ("filter_name", "filter_parameters"),
    [
        (
            "mosaic",
            {
                "tile_size": 2,
                "gap": 0,
                "stagger": 0,
                "_canvas_bounds": (0, 0, 2, 2),
            },
        ),
        ("crystal", {"cell_size": 2, "gap": 0}),
        (
            "spiral",
            {"twist": .7, "falloff": 1.2, "center_x": .5, "center_y": .5},
        ),
        (
            "glitch",
            {
                "slice_height": 2,
                "fragment_width": 2,
                "shift_amount": 1,
                "echo_count": 0,
                "density": .5,
                "seed": 1,
                "_canvas_bounds": (0, 0, 2, 2),
            },
        ),
        (
            "deep_fryer",
            {
                "block_size": 2,
                "band_height": 2,
                "compression_gap": 0,
                "smear_amount": 1,
                "echo_count": 0,
                "degradation": 0,
                "seed": 1,
                "_canvas_bounds": (0, 0, 2, 2),
            },
        ),
    ],
)
def test_large_memory_intensive_filter_uses_streaming_serial_layer_path(
    monkeypatch,
    filter_name,
    filter_parameters,
):
    pixel_boxes = {
        "#FF0000": [box(0, 0, 1, 1), box(1, 0, 2, 1)],
        "#0000FF": [box(0, 1, 1, 2), box(1, 1, 2, 2)],
    }
    monkeypatch.setattr(
        vector_processing,
        "MEMORY_INTENSIVE_FILTER_SERIAL_THRESHOLD",
        1,
    )

    with patch.dict("os.environ", {"RASTER_WORKER_PROCESSES": "2"}):
        with patch.object(
            vector_processing,
            "ThreadPoolExecutor",
            side_effect=AssertionError(
                f"large {filter_name} layers must run serially"
            ),
        ):
            result = vector_processing.process_color_layers(
                pixel_boxes_by_color=pixel_boxes,
                target_colors={
                    "#FF0000": (0, 2, "Red"),
                    "#0000FF": (240, 1, "Blue"),
                },
                min_island_area=0,
                simplification_factor=0,
                smoothing_radius=0,
                abstract_filter=filter_name,
                filter_parameters=filter_parameters,
            )

    assert list(result) == ["#FF0000", "#0000FF"]
    assert pixel_boxes == {}


def test_empty_source_black_stays_empty_instead_of_becoming_a_canvas():
    result = vector_processing.build_source_black_component_layer(
        black_pixel_boxes=[],
        processed_layers={"#FF0000": box(0, 0, 3, 3)},
        black_hex="#000000",
        worker_count=2,
    )

    assert result.is_empty


def test_removed_color_islands_are_returned_for_source_black_reclamation():
    pixel_boxes = {
        "#FF0000": [box(0, 0, 1, 1), box(3, 0, 4, 1)],
    }

    processed, removed_batches = vector_processing.process_color_layers(
        pixel_boxes_by_color=pixel_boxes,
        target_colors={"#FF0000": (0, 2, "Red")},
        min_island_area=2,
        simplification_factor=0,
        smoothing_radius=0,
        abstract_filter="none",
        collect_removed_islands=True,
    )

    assert processed["#FF0000"].is_empty
    assert len(removed_batches) == 1
    assert removed_batches[0].area == 2


def test_reclaimed_islands_fill_source_black_cleanup_holes():
    removed_island = box(1, 0, 2, 1)
    black_components = [box(0, 0, 1, 1), removed_island]

    result = vector_processing.build_source_black_component_layer(
        black_pixel_boxes=(),
        black_rectangles=black_components,
        processed_layers={"#FF0000": box(2, 0, 3, 1)},
        black_hex="#000000",
        worker_count=1,
    )

    assert result.area == 2
    assert result.distance(box(2, 0, 3, 1)) == 0


@pytest.mark.parametrize(
    ("filter_name", "parameters"),
    [
        ("wave", {"amplitude_x": 2, "amplitude_y": 1, "frequency_x": .2, "frequency_y": .15}),
        ("shear", {"shear_x": .4, "shear_y": .1, "scale_x": 1, "scale_y": .9}),
        ("spiral", {"twist": .7, "falloff": 1.2, "center_x": .5, "center_y": .5}),
        ("ripple", {"amplitude": 1.5, "frequency": .2, "phase": .3, "center_x": .5, "center_y": .5}),
        ("mosaic", {"tile_size": 3, "gap": .2, "stagger": .5}),
        ("crystal", {"cell_size": 3, "gap": .2}),
        (
            "glitch",
            {
                "slice_height": 2,
                "fragment_width": 3,
                "shift_amount": 2,
                "echo_count": 1,
                "echo_spacing": 1,
                "density": .65,
                "vertical_jitter": 1,
                "seed": 7,
            },
        ),
        (
            "deep_fryer",
            {
                "block_size": 3,
                "band_height": 2,
                "compression_gap": .2,
                "smear_amount": 2,
                "echo_count": 1,
                "echo_spacing": 1,
                "degradation": .2,
                "seed": 9,
            },
        ),
    ],
)
def test_source_black_uses_same_supported_abstract_transform(filter_name, parameters):
    black_pixels = [box(x, y, x + 1, y + 1) for y in range(2) for x in range(3)]
    parameters = {**parameters, "_canvas_bounds": (0, 0, 6, 4)}

    result = vector_processing.build_source_black_component_layer(
        black_pixel_boxes=black_pixels,
        processed_layers={},
        black_hex="#000000",
        worker_count=2,
        abstract_filter=filter_name,
        filter_parameters=parameters,
    )
    expected = GeometryCollection([
        vector_processing.apply_abstract_filter(pixel, filter_name, parameters)
        for pixel in vector_processing._raster_boxes_to_rectangles(black_pixels)
    ])

    assert unary_union(result).symmetric_difference(unary_union(expected)).area <= 1e-9
    assert result.is_valid


def test_glitch_source_black_shared_field_matches_per_component_transform():
    black_pixels = [
        box(0, 0, 1, 1),
        box(2, 0, 3, 1),
        box(5, 1, 6, 2),
        box(1, 4, 2, 5),
        box(6, 5, 7, 6),
    ]
    rectangles = vector_processing._raster_boxes_to_rectangles(black_pixels)
    parameters = {
        "slice_height": 2,
        "fragment_width": 3,
        "shift_amount": 2,
        "echo_count": 2,
        "echo_spacing": 1,
        "density": .7,
        "fibonacci_stride": 2,
        "vertical_jitter": 1,
        "seed": 11,
        "_canvas_bounds": (0, 0, 8, 7),
    }

    serial = vector_processing.build_source_black_component_layer(
        black_pixel_boxes=(),
        black_rectangles=rectangles,
        processed_layers={},
        black_hex="#000000",
        worker_count=1,
        abstract_filter="glitch",
        filter_parameters=parameters,
    )
    parallel = vector_processing.build_source_black_component_layer(
        black_pixel_boxes=(),
        black_rectangles=rectangles,
        processed_layers={},
        black_hex="#000000",
        worker_count=2,
        abstract_filter="glitch",
        filter_parameters=parameters,
    )
    expected = unary_union([
        vector_processing.apply_abstract_filter(item, "glitch", parameters)
        for item in rectangles
    ])

    assert serial.wkb == parallel.wkb
    assert unary_union(parallel).symmetric_difference(expected).area <= 1e-9
    assert all(not item.interiors for item in parallel.geoms)


def test_deep_fryer_source_black_shared_field_matches_per_component_transform():
    black_pixels = [
        box(0, 0, 1, 1),
        box(2, 0, 3, 1),
        box(5, 1, 6, 2),
        box(1, 4, 2, 5),
        box(6, 5, 7, 6),
    ]
    rectangles = vector_processing._raster_boxes_to_rectangles(black_pixels)
    parameters = {
        "block_size": 3,
        "band_height": 2,
        "compression_gap": .3,
        "smear_amount": 2,
        "echo_count": 2,
        "echo_spacing": 1,
        "degradation": .25,
        "seed": 13,
        "_canvas_bounds": (0, 0, 8, 7),
    }

    serial = vector_processing.build_source_black_component_layer(
        black_pixel_boxes=(),
        black_rectangles=rectangles,
        processed_layers={},
        black_hex="#000000",
        worker_count=1,
        abstract_filter="deep_fryer",
        filter_parameters=parameters,
    )
    parallel = vector_processing.build_source_black_component_layer(
        black_pixel_boxes=(),
        black_rectangles=rectangles,
        processed_layers={},
        black_hex="#000000",
        worker_count=2,
        abstract_filter="deep_fryer",
        filter_parameters=parameters,
    )
    expected = unary_union([
        vector_processing.apply_abstract_filter(item, "deep_fryer", parameters)
        for item in rectangles
    ])

    assert serial.wkb == parallel.wkb
    assert unary_union(parallel).symmetric_difference(expected).area <= 1e-9
    assert all(not item.interiors for item in parallel.geoms)


def test_source_black_assigns_sub_two_pixel_overlap_to_color(monkeypatch):
    black_pixels = [box(x, 0, x + 1, 1) for x in range(4)]
    colored_layer = box(2.5, 0, 4, 1)
    processed_layers = {"#FF0000": colored_layer}
    original_difference = BaseGeometry.difference
    difference_calls = 0

    def leave_first_overlap_in_place(self, other, *args, **kwargs):
        nonlocal difference_calls
        difference_calls += 1
        if difference_calls == 1:
            return self
        return original_difference(self, other, *args, **kwargs)

    monkeypatch.setattr(
        BaseGeometry,
        "difference",
        leave_first_overlap_in_place,
    )

    result = vector_processing.build_source_black_component_layer(
        black_pixel_boxes=black_pixels,
        processed_layers=processed_layers,
        black_hex="#000000",
        worker_count=1,
    )

    assert processed_layers["#FF0000"].equals(colored_layer)
    assert result.area == 2.5
    assert result.intersection(colored_layer).area <= 1e-6


def test_source_black_discards_mixed_dimension_overlay_artifacts(monkeypatch):
    black_pixels = [box(x, 0, x + 1, 1) for x in range(4)]
    colored_layer = box(2.5, 0, 4, 1)
    processed_layers = {"#FF0000": colored_layer}
    original_difference = BaseGeometry.difference
    difference_calls = 0

    def leave_polygon_and_line_artifact(self, other, *args, **kwargs):
        nonlocal difference_calls
        difference_calls += 1
        if difference_calls == 1:
            return GeometryCollection([
                self,
                LineString([(0, 0), (1, 0)]),
            ])
        return original_difference(self, other, *args, **kwargs)

    monkeypatch.setattr(
        BaseGeometry,
        "difference",
        leave_polygon_and_line_artifact,
    )

    result = vector_processing.build_source_black_component_layer(
        black_pixel_boxes=black_pixels,
        processed_layers=processed_layers,
        black_hex="#000000",
        worker_count=1,
    )

    assert processed_layers["#FF0000"].equals(colored_layer)
    assert result.area == 2.5
    assert result.intersection(colored_layer).area <= 1e-6
    assert result.geom_type in {"Polygon", "MultiPolygon", "GeometryCollection"}
    if hasattr(result, "geoms"):
        assert all(item.geom_type == "Polygon" for item in result.geoms)


def test_source_black_normalizes_mixed_dimension_colored_layer():
    colored_polygon = box(2, 0, 4, 2)
    colored_layer = GeometryCollection([
        colored_polygon,
        LineString([(0, 0), (4, 0)]),
    ])
    black_pixels = [box(x, y, x + 1, y + 1) for y in range(2) for x in range(4)]

    result = vector_processing.build_source_black_component_layer(
        black_pixel_boxes=black_pixels,
        processed_layers={"#FF0000": colored_layer},
        black_hex="#000000",
        worker_count=1,
        precision_grid=.001,
    )

    assert result.intersection(colored_polygon).area <= 1e-6
    assert 3.99 <= result.area <= 4.0


def test_source_black_gives_residual_overlap_to_color_without_a_gap(monkeypatch):
    black_pixels = [box(x, 0, x + 1, 1) for x in range(4)]
    colored_layer = box(1, 0, 4, 1)
    processed_layers = {"#FF0000": colored_layer}
    original_difference = BaseGeometry.difference
    difference_calls = 0

    def leave_initial_overlaps_in_place(self, other, *args, **kwargs):
        nonlocal difference_calls
        difference_calls += 1
        if difference_calls == 1:
            return self
        return original_difference(self, other, *args, **kwargs)

    monkeypatch.setattr(BaseGeometry, "difference", leave_initial_overlaps_in_place)

    result = vector_processing.build_source_black_component_layer(
        black_pixel_boxes=black_pixels,
        processed_layers=processed_layers,
        black_hex="#000000",
        worker_count=1,
    )

    assert processed_layers["#FF0000"].equals(colored_layer)
    assert result.area == 1
    assert result.distance(processed_layers["#FF0000"]) == 0


def test_source_black_color_ownership_preserves_the_complete_color(monkeypatch):
    black_pixels = [box(x, 0, x + 1, 1) for x in range(4)]
    processed_layers = {"#FF0000": box(2, 0, 5, 1)}
    original_difference = BaseGeometry.difference
    difference_calls = 0

    def leave_initial_overlap_in_place(self, other, *args, **kwargs):
        nonlocal difference_calls
        difference_calls += 1
        if difference_calls == 1:
            return self
        return original_difference(self, other, *args, **kwargs)

    monkeypatch.setattr(BaseGeometry, "difference", leave_initial_overlap_in_place)

    result = vector_processing.build_source_black_component_layer(
        black_pixel_boxes=black_pixels,
        processed_layers=processed_layers,
        black_hex="#000000",
        worker_count=1,
    )

    corrected_color = processed_layers["#FF0000"]
    assert result.intersection(corrected_color).area <= 1e-6
    assert result.area == 2
    assert corrected_color.area == 3
    assert result.distance(corrected_color) == 0


def test_source_black_mosaic_keeps_black_authoritative(monkeypatch):
    black_pixels = [box(x, 0, x + 1, 1) for x in range(4)]
    processed_layers = {"#FF0000": box(2, 0, 5, 1)}
    original_difference = BaseGeometry.difference
    difference_calls = 0

    def leave_initial_overlap_in_place(self, other, *args, **kwargs):
        nonlocal difference_calls
        difference_calls += 1
        if difference_calls == 1:
            return self
        return original_difference(self, other, *args, **kwargs)

    monkeypatch.setattr(BaseGeometry, "difference", leave_initial_overlap_in_place)
    monkeypatch.setattr(
        vector_processing, "apply_abstract_filter", lambda geometry, *_args: geometry
    )

    result = vector_processing.build_source_black_component_layer(
        black_pixel_boxes=black_pixels,
        processed_layers=processed_layers,
        black_hex="#000000",
        worker_count=1,
        abstract_filter="mosaic",
    )

    corrected_color = processed_layers["#FF0000"]
    assert result.area == 4
    assert result.intersection(corrected_color).area <= 1e-6
    assert .99 <= corrected_color.area < 1.0


def test_source_black_rejects_overlap_when_final_correction_cannot_remove_it(monkeypatch):
    black_pixels = [box(x, 0, x + 1, 1) for x in range(4)]
    colored_layer = box(1, 0, 4, 1)

    monkeypatch.setattr(
        BaseGeometry,
        "difference",
        lambda self, other, *args, **kwargs: self,
    )

    with pytest.raises(ValueError, match="residual-overlap correction failed"):
        vector_processing.build_source_black_component_layer(
            black_pixel_boxes=black_pixels,
            processed_layers={"#FF0000": colored_layer},
            black_hex="#000000",
            worker_count=1,
        )


def test_opt_in_pipeline_exports_sparse_black_without_calling_canvas_punch(tmp_path):
    image = Image.new("RGB", (3, 3), (0, 0, 0))
    image.putpixel((1, 1), (255, 0, 0))
    image_path = tmp_path / "outlined.png"
    output_path = tmp_path / "outlined.svg"
    image.save(image_path)

    project = lightburn.Lightburn()
    vector_processing.lightburn = lightburn
    with patch.dict("os.environ", {"RASTER_SOURCE_BLACK_COMPONENTS": "true"}):
        with patch.object(
            vector_processing,
            "build_punched_black_layer",
            side_effect=AssertionError("canvas punch must not run in source-Black mode"),
        ):
            vector_processing.raster_to_puzzle_and_lightburn(
                raster_image_path=image_path,
                output_svg_path=str(output_path),
                new_height=0,
                new_width=3,
                lb_project_instance=project,
                TARGET_COLORS={
                    "#000000": (0, 0, "Black"),
                    "#FF0000": (0, 2, "Red"),
                },
                scale_factor=1,
                image_preset="cartoon",
                abstract_filter="none",
            )

    black_shapes = [item for item in project.objects if item._layer == 0]
    assert black_shapes
    black_area = sum(
        Polygon(item.points).area
        for item in black_shapes
    )
    assert 7.99 <= black_area <= 8.0
    assert output_path.exists()
    assert Path(str(output_path) + ".lbrn2").exists()


@pytest.mark.parametrize(
    "filter_name",
    [
        "wave", "shear", "spiral", "ripple", "mosaic", "crystal",
        "glitch", "deep_fryer",
    ],
)
def test_supported_filter_exports_transformed_source_black_without_canvas_punch(
    tmp_path, filter_name
):
    image = Image.new("RGB", (5, 5), (0, 0, 0))
    image.putpixel((2, 2), (255, 0, 0))
    image_path = tmp_path / f"{filter_name}.png"
    output_path = tmp_path / f"{filter_name}.svg"
    image.save(image_path)

    project = lightburn.Lightburn()
    vector_processing.lightburn = lightburn
    with patch.dict("os.environ", {"RASTER_SOURCE_BLACK_COMPONENTS": "true"}):
        with patch.object(
            vector_processing,
            "build_punched_black_layer",
            side_effect=AssertionError("canvas punch must not run for supported filters"),
        ):
            vector_processing.raster_to_puzzle_and_lightburn(
                raster_image_path=image_path,
                output_svg_path=str(output_path),
                new_height=0,
                new_width=5,
                lb_project_instance=project,
                TARGET_COLORS={
                    "#000000": (0, 0, "Black"),
                    "#FF0000": (0, 2, "Red"),
                },
                scale_factor=1,
                image_preset="cartoon",
                abstract_filter=filter_name,
            )

    assert any(item._layer == 0 for item in project.objects)
    assert output_path.exists()


def test_supported_filter_validation_failure_falls_back_to_canvas_punch(tmp_path):
    image = Image.new("RGB", (3, 3), (0, 0, 0))
    image.putpixel((1, 1), (255, 0, 0))
    image_path = tmp_path / "wave-fallback.png"
    output_path = tmp_path / "wave-fallback.svg"
    image.save(image_path)

    project = lightburn.Lightburn()
    vector_processing.lightburn = lightburn
    with patch.dict("os.environ", {"RASTER_SOURCE_BLACK_COMPONENTS": "true"}):
        with patch.object(
            vector_processing,
            "build_source_black_component_layer",
            side_effect=ValueError("forced validation failure"),
        ):
            with patch.object(
                vector_processing,
                "build_punched_black_layer",
                wraps=vector_processing.build_punched_black_layer,
            ) as canvas_punch:
                vector_processing.raster_to_puzzle_and_lightburn(
                    raster_image_path=image_path,
                    output_svg_path=str(output_path),
                    new_height=0,
                    new_width=3,
                    lb_project_instance=project,
                    TARGET_COLORS={
                        "#000000": (0, 0, "Black"),
                        "#FF0000": (0, 2, "Red"),
                    },
                    scale_factor=1,
                    image_preset="cartoon",
                    abstract_filter="wave",
                    export_lightburn=False,
                )

    assert canvas_punch.called
    assert output_path.exists()


def test_disabled_flag_keeps_established_canvas_pipeline(tmp_path):
    image = Image.new("RGB", (3, 3), (0, 0, 0))
    image.putpixel((1, 1), (255, 0, 0))
    image_path = tmp_path / "fallback.png"
    output_path = tmp_path / "fallback.svg"
    image.save(image_path)

    project = lightburn.Lightburn()
    vector_processing.lightburn = lightburn
    with patch.dict("os.environ", {"RASTER_SOURCE_BLACK_COMPONENTS": "false"}):
        with patch.object(
            vector_processing,
            "build_source_black_component_layer",
            side_effect=AssertionError("source-Black path must remain disabled"),
        ) as source_builder:
            with patch.object(
                vector_processing,
                "build_black_canvas",
                wraps=vector_processing.build_black_canvas,
            ) as canvas_builder:
                vector_processing.raster_to_puzzle_and_lightburn(
                    raster_image_path=image_path,
                    output_svg_path=str(output_path),
                    new_height=0,
                    new_width=3,
                    lb_project_instance=project,
                    TARGET_COLORS={
                        "#000000": (0, 0, "Black"),
                        "#FF0000": (0, 2, "Red"),
                    },
                    scale_factor=1,
                    image_preset="cartoon",
                    abstract_filter="none",
                    export_lightburn=False,
                )

    source_builder.assert_not_called()
    assert canvas_builder.called
    assert output_path.exists()

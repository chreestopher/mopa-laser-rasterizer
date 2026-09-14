import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from shapely.geometry import box


ROOT = Path(__file__).resolve().parents[1]
LIB_DIR = ROOT / "lib"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(LIB_DIR))

import vector_processing
from abstract_filters import krasnow_grating
from routes.holographic import _assign_holographic_layers, _nearest_recipe


class ParallelWorkerEquivalenceTests(unittest.TestCase):
    def test_parallel_raster_layers_are_byte_identical_to_serial_layers(self):
        pixel_boxes = {
            "#FF0000": [box(0, 0, 1, 1), box(1, 0, 2, 1), box(0, 1, 1, 2)],
            "#00E000": [box(3, 0, 4, 1), box(3, 1, 4, 2), box(4, 1, 5, 2)],
            "#0000FF": [box(0, 3, 1, 4), box(1, 3, 2, 4)],
        }
        target_colors = {
            "#FF0000": (0, 2, "Red"),
            "#00E000": (0, 3, "Green"),
            "#0000FF": (0, 1, "Blue"),
        }
        arguments = dict(
            target_colors=target_colors,
            min_island_area=0,
            simplification_factor=0.0,
            smoothing_radius=0.001,
            abstract_filter="none",
            filter_parameters={"_canvas_bounds": (0, 0, 5, 4), "_scale_factor": 1},
        )
        with patch.dict(os.environ, {"RASTER_WORKER_PROCESSES": "1"}):
            serial = vector_processing.process_color_layers(
                pixel_boxes_by_color={key: list(value) for key, value in pixel_boxes.items()},
                **arguments,
            )
        with patch.dict(os.environ, {"RASTER_WORKER_PROCESSES": "2"}):
            parallel = vector_processing.process_color_layers(
                pixel_boxes_by_color={key: list(value) for key, value in pixel_boxes.items()},
                **arguments,
            )

        self.assertEqual(list(parallel), list(serial))
        self.assertEqual(
            {key: value.wkb for key, value in parallel.items()},
            {key: value.wkb for key, value in serial.items()},
        )

    def test_parallel_holographic_assignment_matches_legacy_per_pixel_path(self):
        pixels = np.random.default_rng(20260827).integers(
            0, 256, size=(17, 19, 3), dtype=np.uint8
        )
        recipes = [
            {"name": "red", "observed_rgb": [210, 38, 45]},
            {"name": "green", "observed_rgb": [35, 190, 80]},
            {"name": "blue", "observed_rgb": [40, 70, 220]},
            {"name": "custom", "observed_rgb": [120, 90, 160], "observed_lab": [48.2, 22.1, -31.7]},
        ]
        legacy = np.empty(pixels.shape[:2], dtype=np.int16)
        for y, row in enumerate(pixels):
            for x, pixel in enumerate(row):
                selected = _nearest_recipe(pixel, recipes)
                legacy[y, x] = recipes.index(selected)

        serial = _assign_holographic_layers(pixels, recipes, workers=1)
        parallel = _assign_holographic_layers(pixels, recipes, workers=2)

        self.assertTrue(np.array_equal(serial, legacy))
        self.assertTrue(np.array_equal(parallel, legacy))

    def test_parallel_krasnow_mapping_is_byte_identical_to_serial_mapping(self):
        processed_layers = {
            "#FF0000": box(0.05, 0.05, 2.75, 2.35),
            "#00E000": box(1.15, 1.05, 4.45, 3.75),
            "#0000FF": box(3.05, 0.25, 5.85, 2.95),
            "#000000": box(0, 0, 6, 0.1),
        }
        target_colors = {
            "#FF0000": (0, 2, "Red"),
            "#00E000": (0, 3, "Green"),
            "#0000FF": (0, 1, "Blue"),
            "#000000": (0, 0, "Black"),
        }
        settings = {
            "_canvas_bounds": (0, 0, 6, 4),
            "_scale_factor": 1,
            "patch_size_mm": 0.4,
            "line_spacing_mm": 0.06,
            "angle_min": -73,
            "angle_max": 81,
        }

        with patch.dict(os.environ, {"RASTER_WORKER_PROCESSES": "1"}):
            serial = krasnow_grating.remap_layers(
                processed_layers, target_colors, settings
            )
        with patch.dict(os.environ, {"RASTER_WORKER_PROCESSES": "2"}):
            parallel = krasnow_grating.remap_layers(
                processed_layers, target_colors, settings
            )

        self.assertEqual(list(parallel), list(serial))
        self.assertEqual(
            {key: value.wkb for key, value in parallel.items()},
            {key: value.wkb for key, value in serial.items()},
        )

        with patch.dict(os.environ, {
            "RASTER_WORKER_PROCESSES": "2",
            "RASTER_KRASNOW_PROGRESS": "false",
        }):
            without_progress = krasnow_grating.remap_layers(
                processed_layers, target_colors, settings
            )
        self.assertEqual(
            {key: value.wkb for key, value in without_progress.items()},
            {key: value.wkb for key, value in serial.items()},
        )

    def test_parallel_black_cleanup_is_byte_identical_to_serial_cleanup(self):
        processed_layers = {
            "#FF0000": box(0.5, 0.5, 2.5, 2.5),
            "#00E000": box(3.0, 1.0, 5.5, 4.0),
            "#0000FF": box(1.5, 3.0, 4.0, 5.5),
        }
        arguments = dict(
            width=6,
            height=6,
            processed_layers=processed_layers,
            black_hex="#000000",
            abstract_filter="none",
            filter_parameters={},
        )
        with patch.dict(os.environ, {"RASTER_WORKER_PROCESSES": "1"}):
            serial = vector_processing.build_punched_black_layer(**arguments)
        with patch.dict(os.environ, {"RASTER_WORKER_PROCESSES": "2"}):
            parallel = vector_processing.build_punched_black_layer(**arguments)

        self.assertEqual(parallel.wkb, serial.wkb)


if __name__ == "__main__":
    unittest.main()

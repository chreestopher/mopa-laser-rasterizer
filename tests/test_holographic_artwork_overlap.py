import ast
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]


def load_geometry_helpers():
    tree = ast.parse((ROOT / "routes" / "holographic.py").read_text(encoding="utf-8"))
    wanted = {"_coalesce_adjacent_rectangles", "_merge_recipe_pixels"}
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    namespace = {"np": np}
    exec(compile(ast.Module(body=functions, type_ignores=[]), "holographic-geometry", "exec"), namespace)
    return namespace["_merge_recipe_pixels"]


class HolographicArtworkOverlapTests(unittest.TestCase):
    def test_preserved_black_pixels_are_excluded_from_recipe_rectangles(self):
        merge_recipe_pixels = load_geometry_helpers()
        layer_map = np.array([
            [0, 0, 1],
            [0, 1, 1],
        ], dtype=np.int16)
        black_mask = np.array([
            [True, False, False],
            [False, True, False],
        ], dtype=bool)

        rectangles = merge_recipe_pixels(layer_map, 2, excluded_mask=black_mask)
        coverage = np.zeros(layer_map.shape, dtype=np.uint8)
        for layer_rectangles in rectangles.values():
            for x, y, width, height in layer_rectangles:
                coverage[y:y + height, x:x + width] += 1

        np.testing.assert_array_equal(coverage[black_mask], np.zeros(2, dtype=np.uint8))
        np.testing.assert_array_equal(coverage[~black_mask], np.ones(4, dtype=np.uint8))

    def test_excluded_mask_must_match_artwork_dimensions(self):
        merge_recipe_pixels = load_geometry_helpers()
        with self.assertRaisesRegex(ValueError, "does not match"):
            merge_recipe_pixels(
                np.zeros((2, 2), dtype=np.int16),
                1,
                excluded_mask=np.zeros((1, 2), dtype=bool),
            )


if __name__ == "__main__":
    unittest.main()

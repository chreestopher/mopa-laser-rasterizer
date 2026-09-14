import sys
from pathlib import Path

from shapely.geometry import box


ROOT = Path(__file__).resolve().parents[1]
LIB_DIR = ROOT / "lib"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(LIB_DIR))

import vector_processing


RED = "#FF0000"
BLUE = "#0000FF"
GREEN = "#00E000"
BLACK = "#000000"


def raster_boxes(assignments):
    grouped = {}
    for (x, y), color in assignments.items():
        grouped.setdefault(color, []).append(box(x, y, x + 1, y + 1))
    return grouped


def owned_cells(grouped):
    result = {}
    for color, boxes in grouped.items():
        for item in boxes:
            result[(int(item.bounds[0]), int(item.bounds[1]))] = color
    return result


def test_small_island_transfers_to_color_touching_most_sides():
    assignments = {
        (1, 1): RED,
        (0, 1): BLUE,
        (1, 0): BLUE,
        (1, 2): BLUE,
        (2, 1): GREEN,
        (0, 0): BLUE,
        (0, 2): BLUE,
        (2, 0): GREEN,
        (2, 2): GREEN,
    }

    reassigned, stats = vector_processing.reassign_small_raster_islands(
        raster_boxes(assignments),
        min_island_area=2,
        color_order=(BLACK, BLUE, GREEN, RED),
        black_hex=BLACK,
    )

    assert owned_cells(reassigned)[(1, 1)] == BLUE
    assert stats["neighbor_components"] == 1
    assert stats["pixels"] == 1


def test_equal_shared_sides_use_stable_palette_order():
    assignments = {
        (1, 1): RED,
        (0, 1): BLUE,
        (2, 1): GREEN,
        (0, 0): BLUE,
        (2, 0): GREEN,
    }

    reassigned, _ = vector_processing.reassign_small_raster_islands(
        raster_boxes(assignments),
        min_island_area=2,
        color_order=(GREEN, BLUE, RED),
        black_hex=BLACK,
    )

    assert owned_cells(reassigned)[(1, 1)] == GREEN


def test_isolated_island_uses_black_fallback_for_filled_artwork():
    reassigned, stats = vector_processing.reassign_small_raster_islands(
        raster_boxes({(4, 7): RED}),
        min_island_area=2,
        color_order=(BLACK, RED),
        black_hex=BLACK,
        fallback_to_black=True,
    )

    assert owned_cells(reassigned) == {(4, 7): BLACK}
    assert stats["black_fallback_components"] == 1


def test_isolated_island_is_discarded_for_transparent_artwork():
    reassigned, stats = vector_processing.reassign_small_raster_islands(
        raster_boxes({(4, 7): RED}),
        min_island_area=2,
        color_order=(BLACK, RED),
        black_hex=BLACK,
        fallback_to_black=False,
    )

    assert owned_cells(reassigned) == {}
    assert stats["discarded_components"] == 1


def test_reassignment_preserves_total_area_and_single_ownership():
    assignments = {
        (0, 0): BLUE,
        (1, 0): RED,
        (2, 0): GREEN,
        (0, 1): BLUE,
        (1, 1): BLUE,
        (2, 1): GREEN,
    }
    source = raster_boxes(assignments)
    source_area = sum(item.area for boxes in source.values() for item in boxes)

    reassigned, _ = vector_processing.reassign_small_raster_islands(
        source,
        min_island_area=2,
        color_order=(BLUE, GREEN, RED),
        black_hex=BLACK,
    )

    cells = owned_cells(reassigned)
    output_area = sum(item.area for boxes in reassigned.values() for item in boxes)
    assert len(cells) == len(assignments)
    assert output_area == source_area
    assert cells[(1, 0)] == BLUE


def test_adjacent_small_islands_cannot_swap_colors_and_survive_cleanup():
    """Assignments must observe earlier merges instead of using a stale snapshot."""
    assignments = {
        (0, 0): RED,
        (1, 0): BLUE,
        (2, 0): GREEN,
        (3, 0): GREEN,
        (4, 0): GREEN,
    }

    reassigned, stats = vector_processing.reassign_small_raster_islands(
        raster_boxes(assignments),
        min_island_area=3,
        color_order=(RED, BLUE, GREEN),
        black_hex=BLACK,
    )

    # The former simultaneous implementation changed Red -> Blue and
    # Blue -> Red from the same input snapshot, leaving two one-cell islands.
    assert owned_cells(reassigned) == {(x, 0): GREEN for x in range(5)}
    assert stats["pixels"] == 2

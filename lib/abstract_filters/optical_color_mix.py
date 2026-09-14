"""Hybrid direct-vector and perceptual two-swatch color synthesis.

The source image supplies the desired color for each mixing cell. Available
LightBurn swatches supply the candidate colors. Cells adequately represented
by a direct swatch retain the ordinary processed vector regions. Only cells
better represented by a two-swatch ratio become deterministic dot matrices,
and every physical dot belongs to exactly one output layer.
"""

import colorsys
import math

import numpy as np
from PIL import Image
from shapely.geometry import Point, box
from shapely.ops import unary_union
from shapely.prepared import prep

from .common import number


USES_SOURCE_COLOR = True
PRESERVE_SOURCE_BLACK = True

DEFAULTS = {
    "mixing_model": "lab",
    "dot_pitch_mm": 0.35,
    "mix_cell_dots": 4,
    "dot_size_ratio": 0.72,
    "direct_color_preference": 0.08,
    "hue_shift": 0.0,
    "saturation_gain": 1.0,
    "brightness_gamma": 1.0,
    "dot_influence": 1.0,
    "neutral_bias": 0.0,
    "pattern_seed": 1,
    "square_dots": 0,
    "keep_available_colors_as_vectors": 1,
}

VECTOR_DEFAULTS = {
    "min_island_area": 0,
    "simplification_factor": 0.0,
    "smoothing_radius": 0.001,
}

CONTROLS = (
    ("dot_pitch_mm", 0.15, 3.0, 0.05),
    ("mix_cell_dots", 2, 8, 1),
    ("dot_size_ratio", 0.2, 0.95, 0.01),
    ("direct_color_preference", 0.0, 1.0, 0.01),
    ("hue_shift", -90, 90, 1),
    ("saturation_gain", 0.25, 2.0, 0.05),
    ("brightness_gamma", 0.4, 2.5, 0.05),
    ("dot_influence", 0.25, 4.0, 0.05),
    ("neutral_bias", -1.0, 1.0, 0.05),
    ("pattern_seed", 0, 999999, 1),
    ("square_dots", 0, 1, 1),
    ("keep_available_colors_as_vectors", 0, 1, 1),
)

MAXIMUM_DOTS = 250_000
PROGRESS_BATCHES = 10


def apply(geometry, settings):
    """Preserve source regions until all swatches can share one matrix."""
    return geometry


def _hex_rgb(color_hex):
    return np.asarray(
        [int(color_hex[index:index + 2], 16) / 255.0 for index in (1, 3, 5)],
        dtype=np.float64,
    )


def _srgb_to_linear(rgb):
    rgb = np.asarray(rgb, dtype=np.float64)
    return np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb(rgb):
    rgb = np.clip(np.asarray(rgb, dtype=np.float64), 0.0, 1.0)
    return np.where(rgb <= 0.0031308, 12.92 * rgb, 1.055 * rgb ** (1 / 2.4) - 0.055)


def _srgb_to_lab(rgb):
    linear = _srgb_to_linear(rgb)
    matrix = np.asarray((
        (0.4124564, 0.3575761, 0.1804375),
        (0.2126729, 0.7151522, 0.0721750),
        (0.0193339, 0.1191920, 0.9503041),
    ))
    xyz = np.asarray(linear) @ matrix.T
    xyz = xyz / np.asarray((0.95047, 1.0, 1.08883))
    delta = 6 / 29
    transformed = np.where(
        xyz > delta ** 3,
        np.cbrt(xyz),
        xyz / (3 * delta * delta) + 4 / 29,
    )
    return np.stack((
        116 * transformed[..., 1] - 16,
        500 * (transformed[..., 0] - transformed[..., 1]),
        200 * (transformed[..., 1] - transformed[..., 2]),
    ), axis=-1)


def _correct_swatch(rgb, settings):
    hue, saturation, value = colorsys.rgb_to_hsv(*rgb)
    hue = (hue + number(settings.get("hue_shift"), 0, -90, 90) / 360.0) % 1.0
    saturation = min(1.0, saturation * number(settings.get("saturation_gain"), 1, 0.25, 2))
    gamma = number(settings.get("brightness_gamma"), 1, 0.4, 2.5)
    value = min(1.0, max(0.0, value ** gamma))
    return np.asarray(colorsys.hsv_to_rgb(hue, saturation, value), dtype=np.float64)


def _visual_weight(geometric_weight, influence):
    """Let the minority swatch appear stronger or weaker than its dot count."""
    if geometric_weight in (0.0, 1.0):
        return geometric_weight
    if geometric_weight >= 0.5:
        minority = (1.0 - geometric_weight) * influence
        return 1.0 / (1.0 + minority / geometric_weight)
    minority = geometric_weight * influence
    return minority / (minority + 1.0 - geometric_weight)


def _candidate_space(color_hexes, slots, settings):
    corrected = np.asarray([
        _correct_swatch(_hex_rgb(color_hex), settings) for color_hex in color_hexes
    ])
    influence = number(settings.get("dot_influence"), 1, 0.25, 4)
    neutral_bias = number(settings.get("neutral_bias"), 0, -1, 1)
    candidates = []

    for index, rgb in enumerate(corrected):
        saturation = colorsys.rgb_to_hsv(*rgb)[1]
        neutral_share = 1.0 - saturation
        candidates.append((index, index, slots, rgb, neutral_share, False))

    for first in range(len(color_hexes)):
        for second in range(first + 1, len(color_hexes)):
            first_neutral = 1.0 - colorsys.rgb_to_hsv(*corrected[first])[1]
            second_neutral = 1.0 - colorsys.rgb_to_hsv(*corrected[second])[1]
            for first_count in range(1, slots):
                geometric_weight = first_count / slots
                visual_weight = _visual_weight(geometric_weight, influence)
                linear_mix = (
                    _srgb_to_linear(corrected[first]) * visual_weight
                    + _srgb_to_linear(corrected[second]) * (1.0 - visual_weight)
                )
                mixed_rgb = _linear_to_srgb(linear_mix)
                neutral_share = (
                    first_neutral * visual_weight
                    + second_neutral * (1.0 - visual_weight)
                )
                candidates.append((
                    first, second, first_count, mixed_rgb,
                    neutral_share, True,
                ))

    rgb_values = np.asarray([item[3] for item in candidates])
    penalties = np.asarray([
        (number(settings.get("direct_color_preference"), 0.08, 0, 1) if item[5] else 0.0)
        + neutral_bias * item[4] * 0.25
        for item in candidates
    ])
    return candidates, rgb_values, penalties


def _hsv_distance(candidate_hsv, target):
    target_hsv = np.asarray(colorsys.rgb_to_hsv(*target))
    hue_delta = np.abs(candidate_hsv[:, 0] - target_hsv[0])
    hue_delta = np.minimum(hue_delta, 1.0 - hue_delta)
    return (
        4.0 * hue_delta * hue_delta
        + (candidate_hsv[:, 1] - target_hsv[1]) ** 2
        + (candidate_hsv[:, 2] - target_hsv[2]) ** 2
    )


def _candidate_values(candidates_rgb, model):
    if model == "rgb":
        return _srgb_to_linear(candidates_rgb)
    if model == "hsv":
        return np.asarray([colorsys.rgb_to_hsv(*rgb) for rgb in candidates_rgb])
    return _srgb_to_lab(candidates_rgb)


def _best_candidate(target_rgb, candidate_values, penalties, model):
    if model == "rgb":
        target = _srgb_to_linear(target_rgb)
        values = candidate_values
        distances = np.sum((values - target) ** 2, axis=1)
    elif model == "hsv":
        distances = _hsv_distance(candidate_values, target_rgb)
    else:
        target = _srgb_to_lab(target_rgb)
        values = candidate_values
        # Normalize Lab axes before adding dimensionless user penalties.
        distances = np.sum(((values - target) / np.asarray((100, 128, 128))) ** 2, axis=1)
    return int(np.argmin(distances + penalties))


def _dot_order(size, seed, cell_x, cell_y):
    """Return a deterministic low-clumping order for one mixing cell."""
    center = (size - 1) / 2
    phase = (int(seed) * 0.61803398875 + cell_x * 0.41421356237 + cell_y * 0.73205080757) % 1
    ranked = []
    for y in range(size):
        for x in range(size):
            radial = ((x - center) ** 2 + (y - center) ** 2) / max(size * size, 1)
            sequence = (x * 0.754877666 + y * 0.569840291 + phase) % 1
            ranked.append((sequence + radial * 0.05, y * size + x))
    return [index for _, index in sorted(ranked)]


def remap_layers(processed_layers, target_colors, settings):
    bounds = settings.get("_canvas_bounds")
    nonempty = [geometry for geometry in processed_layers.values() if not geometry.is_empty]
    if not nonempty:
        return {}
    if not bounds or len(bounds) != 4:
        bounds = unary_union(nonempty).bounds
    min_x, min_y, max_x, max_y = map(float, bounds)
    if max_x <= min_x or max_y <= min_y:
        return {}

    scale_factor = number(settings.get("_scale_factor"), 1.0)
    if scale_factor <= 0:
        scale_factor = 1.0
    pitch_mm = number(settings.get("dot_pitch_mm"), 0.35, 0.15, 3)
    pitch = pitch_mm / scale_factor
    cell_dots = int(round(number(settings.get("mix_cell_dots"), 4, 2, 8)))
    dot_ratio = number(settings.get("dot_size_ratio"), 0.72, 0.2, 0.95)
    columns = max(1, math.ceil((max_x - min_x) / pitch))
    rows = max(1, math.ceil((max_y - min_y) / pitch))
    total_dots = columns * rows
    if total_dots > MAXIMUM_DOTS:
        raise ValueError(
            "Optical Color Mix would create "
            f"{total_dots:,} dot positions. Increase Dot Pitch MM until the "
            f"matrix contains no more than {MAXIMUM_DOTS:,} positions."
        )

    color_hexes = [color for color in target_colors if color.startswith("#")]
    if not color_hexes:
        return {}
    slots = cell_dots * cell_dots
    candidates, candidates_rgb, penalties = _candidate_space(
        color_hexes, slots, settings
    )
    model = str(settings.get("mixing_model") or "lab").strip().lower()
    if model not in {"lab", "rgb", "hsv"}:
        model = "lab"
    candidate_values = _candidate_values(candidates_rgb, model)

    source = settings.get("_source_color_image")
    if source is None or not getattr(source, "size", None):
        source = Image.new("RGB", (columns, rows), (127, 127, 127))
    else:
        source = source.convert("RGB")
    mix_columns = max(1, math.ceil(columns / cell_dots))
    mix_rows = max(1, math.ceil(rows / cell_dots))
    sampled = np.asarray(
        source.resize((mix_columns, mix_rows), Image.Resampling.BOX),
        dtype=np.float64,
    ) / 255.0

    artwork_geometry = unary_union(nonempty)
    artwork_mask = prep(artwork_geometry)
    canvas = box(min_x, min_y, max_x, max_y)
    pieces = {color: [] for color in color_hexes}
    vector_cells = []
    mixed_cell_count = 0
    dot_count = 0
    square_dots = number(settings.get("square_dots"), 0, 0, 1) >= 0.5
    keep_available_vectors = number(
        settings.get("keep_available_colors_as_vectors"), 1, 0, 1
    ) >= 0.5
    seed = int(round(number(settings.get("pattern_seed"), 1, 0, 999999)))
    logger = settings.get("_progress_logger")
    if callable(logger):
        logger(
            "Optical Color Mix: starting "
            f"{columns} x {rows} shared-dot matrix grouped into "
            f"{mix_columns} x {mix_rows} mixing cells using {model.upper()} matching."
        )

    progress_interval = max(1, math.ceil(mix_rows / PROGRESS_BATCHES))
    last_reported = 0
    half_size = pitch * dot_ratio / 2
    for cell_y in range(mix_rows):
        for cell_x in range(mix_columns):
            candidate_index = _best_candidate(
                sampled[cell_y, cell_x], candidate_values, penalties, model
            )
            first, second, first_count, _, _, is_mixture = candidates[candidate_index]
            cell_bounds = box(
                min_x + cell_x * cell_dots * pitch,
                min_y + cell_y * cell_dots * pitch,
                min(max_x, min_x + (cell_x + 1) * cell_dots * pitch),
                min(max_y, min_y + (cell_y + 1) * cell_dots * pitch),
            )
            if not artwork_geometry.intersects(cell_bounds):
                continue
            if keep_available_vectors and not is_mixture:
                vector_cells.append(cell_bounds)
                continue

            mixed_cell_count += 1
            order = _dot_order(cell_dots, seed, cell_x, cell_y)
            first_slots = set(order[:first_count])
            for local_y in range(cell_dots):
                row = cell_y * cell_dots + local_y
                if row >= rows:
                    continue
                y = min_y + (row + 0.5) * pitch
                for local_x in range(cell_dots):
                    column = cell_x * cell_dots + local_x
                    if column >= columns:
                        continue
                    x = min_x + (column + 0.5) * pitch
                    center = Point(x, y)
                    if not artwork_mask.covers(center):
                        continue
                    slot = local_y * cell_dots + local_x
                    color_index = first if slot in first_slots else second
                    if square_dots:
                        mark = box(
                            x - half_size, y - half_size,
                            x + half_size, y + half_size,
                        )
                    else:
                        mark = center.buffer(half_size, quad_segs=8)
                    mark = mark.intersection(canvas)
                    if not mark.is_empty:
                        pieces[color_hexes[color_index]].append(mark)
                        dot_count += 1

        completed = cell_y + 1
        if callable(logger) and (
            completed % progress_interval == 0 or completed == mix_rows
        ):
            logger(
                "Optical Color Mix: completed mixing-cell rows "
                f"{last_reported + 1}-{completed} of {mix_rows}."
            )
            last_reported = completed

    if vector_cells:
        vector_region = unary_union(vector_cells).intersection(canvas)
        for color, geometry in processed_layers.items():
            if color not in pieces or geometry.is_empty:
                continue
            retained = geometry.intersection(vector_region)
            if not retained.is_empty:
                pieces[color].append(retained)

    output = {
        color: unary_union(items) for color, items in pieces.items() if items
    }
    if callable(logger):
        logger(
            "Optical Color Mix: hybrid mapping complete with "
            f"{len(vector_cells):,} direct-vector cells and "
            f"{dot_count:,} dots across {mixed_cell_count:,} mixed cells on "
            f"{len(output)} swatch layers."
        )
    return output

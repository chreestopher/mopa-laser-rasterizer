"""Rebuild quantized artwork as ribbons following its structure-tensor flow.

The tensor is calculated once from the resized source luminance.  A shared,
deterministic set of streamlines follows the local tangent field, then each
color receives only the portions inside its mutually-exclusive source region.
"""

import math
from collections import defaultdict

import cv2
import numpy as np
from shapely.geometry import GeometryCollection, LineString, Point, box
from shapely.ops import unary_union

from .common import number


USES_SOURCE_LUMINANCE = True
PRESERVE_SOURCE_BLACK = True

DEFAULTS = {
    "abstraction": 0.5,
    "line_spacing_mm": 0.9,
    "line_length_mm": 5.0,
    "minimum_ribbon_width_mm": 0.10,
    "maximum_ribbon_width_mm": 0.35,
    "minimum_color_run_mm": 0.30,
    "width_tone_influence": 0.65,
    "width_coherence_influence": 0.35,
    "step_size_mm": 0.15,
    "source_blur_px": 1.5,
    "tensor_smoothing_px": 6.0,
    "coherence_cutoff": 0.0,
    "coherence_influence": 0.5,
    "flow_rotation": 0.0,
    "seed_jitter": 0.15,
    "seed": 1,
}

VECTOR_DEFAULTS = {
    "min_island_area": 0,
    "simplification_factor": 0.0,
    "smoothing_radius": 0.001,
}

CONTROLS = (
    ("abstraction", 0.0, 1.0, 0.01),
    ("line_spacing_mm", 0.2, 4.0, 0.05),
    ("line_length_mm", 0.5, 20.0, 0.25),
    ("minimum_ribbon_width_mm", 0.02, 1.0, 0.01),
    ("maximum_ribbon_width_mm", 0.02, 2.0, 0.01),
    ("minimum_color_run_mm", 0.0, 5.0, 0.05),
    ("width_tone_influence", 0.0, 1.0, 0.05),
    ("width_coherence_influence", 0.0, 1.0, 0.05),
    ("step_size_mm", 0.03, 0.5, 0.01),
    ("source_blur_px", 0.0, 8.0, 0.1),
    ("tensor_smoothing_px", 0.5, 20.0, 0.5),
    ("coherence_cutoff", 0.0, 1.0, 0.01),
    ("coherence_influence", 0.0, 1.0, 0.05),
    ("flow_rotation", -90.0, 90.0, 1.0),
    ("seed_jitter", 0.0, 0.45, 0.01),
    ("seed", 0, 999999, 1),
)

MAXIMUM_SEEDS = 80_000
PROGRESS_BATCHES = 10


def apply(geometry, settings):
    """Wait until all cleaned layers are available for one shared flow field."""
    return geometry


def _effective_settings(settings):
    """Coordinate detail controls around one Photorealistic/Abstract axis."""
    values = dict(settings)
    abstraction = number(values.get("abstraction"), 0.5, 0, 1)
    # Photorealistic: dense, broad, local marks retain more color silhouette.
    # Abstract: sparse, thin, long marks follow a broadly averaged flow field.
    values["line_spacing_mm"] = number(
        values.get("line_spacing_mm"), 0.9, 0.02, 20
    ) * (0.35 + 1.45 * abstraction)
    values["line_length_mm"] = number(
        values.get("line_length_mm"), 5, 0.05, 100
    ) * (0.65 + 0.85 * abstraction)
    width_factor = 1.6 - 0.7 * abstraction
    minimum_width = number(
        values.get("minimum_ribbon_width_mm"), 0.10, 0.005, 5
    ) * width_factor
    maximum_width = number(
        values.get("maximum_ribbon_width_mm"), 0.35, 0.005, 5
    ) * width_factor
    values["minimum_ribbon_width_mm"] = min(minimum_width, maximum_width)
    values["maximum_ribbon_width_mm"] = max(minimum_width, maximum_width)
    values["source_blur_px"] = number(
        values.get("source_blur_px"), 1.5, 0, 20
    ) * (0.45 + 1.55 * abstraction)
    values["tensor_smoothing_px"] = number(
        values.get("tensor_smoothing_px"), 6, 0.1, 50
    ) * (0.45 + 1.75 * abstraction)
    values["coherence_influence"] = min(
        1.0,
        number(values.get("coherence_influence"), 0.5, 0, 1)
        * (0.35 + 1.3 * abstraction),
    )
    values["seed_jitter"] = number(
        values.get("seed_jitter"), 0.15, 0, 0.45
    ) * (0.25 + 0.75 * abstraction)
    return values


def _tensor_field(image, settings):
    if image is None or not getattr(image, "size", None):
        raise ValueError("Structure Tensor Flow requires the source image luminance.")
    luminance = np.asarray(image.convert("L"), dtype=np.float32) / 255.0
    source_blur = number(settings.get("source_blur_px"), 1.5, 0, 20)
    if source_blur > 0:
        luminance = cv2.GaussianBlur(
            luminance, (0, 0), sigmaX=source_blur, sigmaY=source_blur
        )
    gradient_x = cv2.Sobel(luminance, cv2.CV_32F, 1, 0, ksize=3)
    gradient_y = cv2.Sobel(luminance, cv2.CV_32F, 0, 1, ksize=3)
    tensor_sigma = number(settings.get("tensor_smoothing_px"), 6, 0.1, 50)
    tensor_xx = cv2.GaussianBlur(
        gradient_x * gradient_x, (0, 0), sigmaX=tensor_sigma, sigmaY=tensor_sigma
    )
    tensor_xy = cv2.GaussianBlur(
        gradient_x * gradient_y, (0, 0), sigmaX=tensor_sigma, sigmaY=tensor_sigma
    )
    tensor_yy = cv2.GaussianBlur(
        gradient_y * gradient_y, (0, 0), sigmaX=tensor_sigma, sigmaY=tensor_sigma
    )
    difference = tensor_xx - tensor_yy
    magnitude = np.sqrt(difference * difference + 4.0 * tensor_xy * tensor_xy)
    coherence = magnitude / (tensor_xx + tensor_yy + 1e-12)
    # The principal eigenvector points across an edge. Add 90 degrees so the
    # emitted structures flow along contours and visible forms instead.
    tangent = 0.5 * np.arctan2(2.0 * tensor_xy, difference) + math.pi / 2.0
    return tangent, np.clip(coherence, 0.0, 1.0), luminance


def _sample(field, x, y, bounds):
    height, width = field.shape
    min_x, min_y, max_x, max_y = bounds
    image_x = (x - min_x) / max(max_x - min_x, 1e-9) * max(width - 1, 0)
    image_y = (y - min_y) / max(max_y - min_y, 1e-9) * max(height - 1, 0)
    image_x = min(width - 1, max(0.0, image_x))
    image_y = min(height - 1, max(0.0, image_y))
    left, top = int(math.floor(image_x)), int(math.floor(image_y))
    right, bottom = min(width - 1, left + 1), min(height - 1, top + 1)
    x_mix, y_mix = image_x - left, image_y - top
    return float(
        field[top, left] * (1 - x_mix) * (1 - y_mix)
        + field[top, right] * x_mix * (1 - y_mix)
        + field[bottom, left] * (1 - x_mix) * y_mix
        + field[bottom, right] * x_mix * y_mix
    )


def _direction(tangent, x, y, bounds, rotation, previous=None, direction=1):
    angle = _sample(tangent, x, y, bounds) + rotation
    vector = (math.cos(angle) * direction, math.sin(angle) * direction)
    # A structure tensor is an undirected axis. Keep its sign continuous while
    # integrating so streamlines do not oscillate forward and backward.
    if previous is not None and vector[0] * previous[0] + vector[1] * previous[1] < 0:
        vector = (-vector[0], -vector[1])
    return vector


def _trace(
    seed_x,
    seed_y,
    tangent,
    coherence,
    bounds,
    settings,
    direction,
):
    scale = number(settings.get("_scale_factor"), 1, 1e-6, 1e6)
    step = number(settings.get("step_size_mm"), 0.15, 0.01, 2.0) / scale
    full_length = number(settings.get("line_length_mm"), 5, 0.05, 100) / scale
    influence = number(settings.get("coherence_influence"), 0.5, 0, 1)
    seed_coherence = _sample(coherence, seed_x, seed_y, bounds)
    length_factor = (1.0 - influence) + influence * max(0.15, seed_coherence)
    steps = max(1, int(math.ceil(full_length * length_factor / (2.0 * step))))
    cutoff = number(settings.get("coherence_cutoff"), 0, 0, 1)
    rotation = math.radians(number(settings.get("flow_rotation"), 0, -180, 180))
    min_x, min_y, max_x, max_y = bounds
    x, y = seed_x, seed_y
    points = []
    previous = None
    for _ in range(steps):
        if not (min_x <= x <= max_x and min_y <= y <= max_y):
            break
        if _sample(coherence, x, y, bounds) < cutoff:
            break
        points.append((x, y))
        vector = _direction(
            tangent, x, y, bounds, rotation, previous, direction
        )
        # Midpoint integration follows curved fields more faithfully than a
        # single Euler sample without making the output non-deterministic.
        middle_x = x + vector[0] * step * 0.5
        middle_y = y + vector[1] * step * 0.5
        vector = _direction(
            tangent, middle_x, middle_y, bounds, rotation, vector, direction
        )
        x += vector[0] * step
        y += vector[1] * step
        previous = vector
    return points


def _exclusive_layers(processed_layers, target_colors, canvas):
    ordered = [
        color_hex
        for color_hex, _ in sorted(
            target_colors.items(), key=lambda item: item[1][1]
        )
    ]
    ordered.extend(color for color in processed_layers if color not in target_colors)
    claimed = GeometryCollection()
    result = {}
    for color_hex in ordered:
        geometry = processed_layers.get(color_hex)
        if geometry is None or geometry.is_empty:
            continue
        owned = geometry.intersection(canvas)
        if not claimed.is_empty:
            owned = owned.difference(claimed)
        if owned.is_empty:
            continue
        result[color_hex] = owned
        claimed = owned if claimed.is_empty else claimed.union(owned)
    return result


def _assert_exclusive_layers(layers, tolerance=1e-9):
    nonempty = [(color, geometry) for color, geometry in layers.items() if not geometry.is_empty]
    for index, (left_color, left) in enumerate(nonempty):
        for right_color, right in nonempty[index + 1:]:
            if left.intersects(right) and left.intersection(right).area > tolerance:
                raise ValueError(
                    "Structure Tensor Flow overlap validation failed: "
                    f"{left_color} and {right_color} overlap."
                )


def _ribbon_width(luminance, coherence, x, y, bounds, settings, scale):
    """Map local tone and directional confidence into the requested width range."""
    minimum = number(settings.get("minimum_ribbon_width_mm"), 0.10, 0.005, 5) / scale
    maximum = number(settings.get("maximum_ribbon_width_mm"), 0.35, 0.005, 5) / scale
    minimum, maximum = min(minimum, maximum), max(minimum, maximum)
    tone_weight = number(settings.get("width_tone_influence"), 0.65, 0, 1)
    coherence_weight = number(
        settings.get("width_coherence_influence"), 0.35, 0, 1
    )
    total_weight = tone_weight + coherence_weight
    if total_weight <= 1e-9:
        response = 0.5
    else:
        # Darker image structure carries more visual weight, while coherent
        # tensor regions can safely support a broader, cleaner ribbon.
        darkness = 1.0 - _sample(luminance, x, y, bounds)
        local_coherence = _sample(coherence, x, y, bounds)
        response = (
            tone_weight * darkness + coherence_weight * local_coherence
        ) / total_weight
    return minimum + (maximum - minimum) * min(1.0, max(0.0, response))


def _grid_cells(geometry, bounds, cell_size):
    min_x, min_y, _, _ = bounds
    geom_min_x, geom_min_y, geom_max_x, geom_max_y = geometry.bounds
    left = int(math.floor((geom_min_x - min_x) / cell_size))
    right = int(math.floor((geom_max_x - min_x) / cell_size))
    top = int(math.floor((geom_min_y - min_y) / cell_size))
    bottom = int(math.floor((geom_max_y - min_y) / cell_size))
    for row in range(top, bottom + 1):
        for column in range(left, right + 1):
            yield column, row


def _remove_ribbon_overlaps(
    ribbons, bounds, spacing, maximum_width, logger=None
):
    """Separate parallel contacts and break both marks at true crossings."""
    cell_size = max(spacing, maximum_width, 1e-6)
    spatial_index = defaultdict(list)
    cuts = [[] for _ in ribbons]
    progress_interval = max(1, math.ceil(len(ribbons) / 5))
    for ribbon_index, record in enumerate(ribbons):
        ribbon, _seed_x, _seed_y, width, angle = record
        nearby_indexes = []
        seen = set()
        for cell in _grid_cells(ribbon, bounds, cell_size):
            for prior_index in spatial_index[cell]:
                if prior_index not in seen:
                    seen.add(prior_index)
                    nearby_indexes.append(prior_index)
        for prior_index in nearby_indexes:
            prior, _prior_x, _prior_y, prior_width, prior_angle = ribbons[prior_index]
            junction = ribbon.intersection(prior)
            if junction is None or junction.is_empty:
                continue
            angle_difference = abs(
                (angle - prior_angle + math.pi / 2.0) % math.pi
                - math.pi / 2.0
            )
            if angle_difference >= math.radians(20):
                break_radius = max(min(width, prior_width) * 0.08, 1e-6)
                cut = junction.buffer(
                    break_radius, cap_style=1, join_style=1, quad_segs=2
                )
                cut_both = True
            else:
                # Parallel ribbons use deterministic painter order. The tiny
                # buffer keeps their boundaries disconnected without visibly
                # reducing the requested density or width.
                cut = prior.buffer(1e-7, cap_style=1, join_style=1, quad_segs=1)
                cut_both = False
            if cut is None or cut.is_empty:
                continue
            cuts[ribbon_index].append(cut)
            if cut_both:
                cuts[prior_index].append(cut)
        for cell in _grid_cells(ribbon, bounds, cell_size):
            spatial_index[cell].append(ribbon_index)
        if callable(logger) and (
            (ribbon_index + 1) % progress_interval == 0
            or ribbon_index + 1 == len(ribbons)
        ):
            logger(
                "Structure Tensor Flow: checked ribbon crossings for "
                f"{ribbon_index + 1}/{len(ribbons)} streamline(s)."
            )

    separated = []
    for ribbon_index, (ribbon, seed_x, seed_y, width, _angle) in enumerate(ribbons):
        if cuts[ribbon_index]:
            ribbon = ribbon.difference(unary_union(cuts[ribbon_index]))
        if not ribbon.is_empty:
            separated.append((ribbon, seed_x, seed_y, width))
    return separated


def _polygon_parts(geometry):
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    if hasattr(geometry, "geoms"):
        return [
            part
            for child in geometry.geoms
            for part in _polygon_parts(child)
        ]
    return []


def _shared_boundary_length(fragment, target):
    """Measure touching edges, tolerating null GEOS results on degenerate parts."""
    fragment_boundary = fragment.boundary
    target_boundary = target.boundary
    if fragment_boundary is None or target_boundary is None:
        return 0.0
    shared_geometry = fragment_boundary.intersection(target_boundary)
    if shared_geometry is not None:
        return float(shared_geometry.length)

    # Some complex or nearly degenerate polygon boundaries can make GEOS return
    # a null result instead of an empty geometry. Approximate the contact length
    # from a scale-relative, outward buffer so color-run cleanup remains useful.
    min_x, min_y, max_x, max_y = fragment.bounds
    span = max(max_x - min_x, max_y - min_y, 1.0)
    tolerance = max(span * 1e-9, 1e-12)
    expanded_target = target.buffer(tolerance)
    if expanded_target is None or expanded_target.is_empty:
        return 0.0
    contact = fragment.intersection(expanded_target)
    if contact is None or contact.is_empty:
        return 0.0
    return float(contact.area) / tolerance


def _merge_short_color_runs(layers, target_colors, minimum_area, logger=None):
    """Give undersized ribbon fragments to the color sharing most boundary."""
    if minimum_area <= 0:
        return layers, 0
    order = [
        color
        for color, _ in sorted(target_colors.items(), key=lambda item: item[1][1])
    ]
    order.extend(color for color in layers if color not in target_colors)
    rank = {color: index for index, color in enumerate(dict.fromkeys(order))}
    result = dict(layers)
    transfers = 0
    candidates = [
        (color, part)
        for color, geometry in result.items()
        for part in _polygon_parts(geometry)
        if part.area < minimum_area
    ]
    candidates.sort(key=lambda item: (item[1].area, rank.get(item[0], len(rank))))
    progress_interval = max(1, math.ceil(len(candidates) / 5)) if candidates else 1
    for candidate_index, (source_color, fragment) in enumerate(candidates, 1):
        if callable(logger) and (
            candidate_index % progress_interval == 0
            or candidate_index == len(candidates)
        ):
            logger(
                "Structure Tensor Flow: evaluating minimum color runs for "
                f"{candidate_index}/{len(candidates)} fragment(s)."
            )
        source = result.get(source_color)
        if source is None or source.is_empty:
            continue
        owned_fragment = fragment.intersection(source)
        if owned_fragment.is_empty or owned_fragment.area >= minimum_area:
            continue
        neighbors = []
        for target_color, target in result.items():
            if target_color == source_color or target.is_empty:
                continue
            shared = _shared_boundary_length(owned_fragment, target)
            if shared > 1e-9:
                neighbors.append((shared, -rank.get(target_color, len(rank)), target_color))
        if not neighbors:
            continue
        target_color = max(neighbors)[2]
        result[source_color] = source.difference(owned_fragment)
        result[target_color] = unary_union([result[target_color], owned_fragment])
        transfers += 1
    return {color: geometry for color, geometry in result.items() if not geometry.is_empty}, transfers


def remap_layers(processed_layers, target_colors, settings):
    settings = _effective_settings(settings)
    bounds = settings.get("_canvas_bounds")
    if not bounds or len(bounds) != 4:
        nonempty = [geometry for geometry in processed_layers.values() if not geometry.is_empty]
        if not nonempty:
            return {}
        bounds = unary_union(nonempty).bounds
    bounds = tuple(map(float, bounds))
    min_x, min_y, max_x, max_y = bounds
    if max_x <= min_x or max_y <= min_y:
        return {}
    canvas = box(*bounds)
    exclusive = _exclusive_layers(processed_layers, target_colors, canvas)
    if not exclusive:
        return {}

    tangent, coherence, luminance = _tensor_field(
        settings.get("_angle_image"), settings
    )
    scale = number(settings.get("_scale_factor"), 1, 1e-6, 1e6)
    spacing = number(settings.get("line_spacing_mm"), 0.9, 0.02, 20) / scale
    minimum_width = number(
        settings.get("minimum_ribbon_width_mm"), 0.10, 0.005, 5
    ) / scale
    maximum_width = number(
        settings.get("maximum_ribbon_width_mm"), 0.35, 0.005, 5
    ) / scale
    minimum_width, maximum_width = (
        min(minimum_width, maximum_width), max(minimum_width, maximum_width)
    )
    jitter = number(settings.get("seed_jitter"), 0.15, 0, 0.45)
    columns = max(1, int(math.ceil((max_x - min_x) / spacing)))
    rows = max(1, int(math.ceil((max_y - min_y) / spacing)))
    seed_count = columns * rows
    if seed_count > MAXIMUM_SEEDS:
        raise ValueError(
            "Structure Tensor Flow would create too many streamlines. "
            "Increase Line Spacing MM or reduce the output dimensions."
        )

    logger = settings.get("_progress_logger")
    if callable(logger):
        logger(
            f"Structure Tensor Flow: starting {seed_count} streamline seeds "
            f"across {rows} row(s)."
        )
    rng = np.random.default_rng(
        int(number(settings.get("seed"), 1, -2147483648, 2147483647))
    )
    candidates = []
    for row in range(rows):
        base_y = min_y + (row + 0.5) * spacing
        offset = spacing * 0.5 if row % 2 else 0.0
        for column in range(columns):
            base_x = min_x + (column + 0.5) * spacing + offset
            x = base_x + rng.uniform(-jitter, jitter) * spacing
            y = base_y + rng.uniform(-jitter, jitter) * spacing
            if not (min_x <= x <= max_x and min_y <= y <= max_y):
                continue
            candidates.append((x, y))

    ribbons = []
    progress_interval = max(1, math.ceil(len(candidates) / PROGRESS_BATCHES))
    for candidate_index, (x, y) in enumerate(candidates, 1):
        backward = _trace(
            x, y, tangent, coherence, bounds, settings, -1
        )
        forward = _trace(
            x, y, tangent, coherence, bounds, settings, 1
        )
        points = list(reversed(backward[1:])) + forward
        if len(points) < 2:
            continue
        centerline = LineString(points)
        start_x, start_y = centerline.coords[0]
        end_x, end_y = centerline.coords[-1]
        centerline_angle = math.atan2(end_y - start_y, end_x - start_x)
        width = _ribbon_width(
            luminance, coherence, x, y, bounds, settings, scale
        )
        if centerline.length < max(width, spacing * 0.25):
            continue
        ribbon = centerline.buffer(
            width / 2.0, cap_style=2, join_style=1, quad_segs=3
        ).intersection(canvas)
        if not ribbon.is_empty:
            ribbons.append((ribbon, x, y, width, centerline_angle))
        if callable(logger) and (
            candidate_index % progress_interval == 0
            or candidate_index == len(candidates)
        ):
            logger(
                "Structure Tensor Flow: evaluated "
                f"{candidate_index}/{len(candidates)} seed candidates; "
                    f"generated {len(ribbons)} streamline(s)."
            )

    if not ribbons:
        return {}
    original_ribbon_count = len(ribbons)
    if callable(logger):
        logger(
            "Structure Tensor Flow: breaking apart intersections among "
            f"{original_ribbon_count} generated ribbon(s)."
        )
    ribbons = _remove_ribbon_overlaps(
        ribbons, bounds, spacing, maximum_width, logger=logger
    )
    if not ribbons:
        return {}
    abstraction = number(settings.get("abstraction"), 0.5, 0, 1)
    # Smoothstep gives the Photorealistic end a useful adjustment range while
    # still reaching a completely free-flowing stroke field at Abstract.
    free_flow_fraction = abstraction * abstraction * (3.0 - 2.0 * abstraction)
    clipped_ribbons = []
    painted_ribbons = {color_hex: [] for color_hex in exclusive}
    free_flow_count = 0
    for ribbon, seed_x, seed_y, _width in ribbons:
        use_free_flow = rng.random() < free_flow_fraction
        owner = None
        if use_free_flow:
            seed_point = Point(seed_x, seed_y)
            for color_hex, source_geometry in exclusive.items():
                if source_geometry.covers(seed_point):
                    owner = color_hex
                    break
        if owner is None:
            clipped_ribbons.append(ribbon)
        else:
            painted_ribbons[owner].append(ribbon)
            free_flow_count += 1

    output = {}
    if callable(logger):
        logger(
            "Structure Tensor Flow: assigning separated ribbons to color layers."
        )
    if clipped_ribbons:
        clipped_flow = unary_union(clipped_ribbons)
        for color_hex, source_geometry in exclusive.items():
            clipped = source_geometry.intersection(clipped_flow)
            if not clipped.is_empty:
                output[color_hex] = clipped
    for color_hex, color_ribbons in painted_ribbons.items():
        if not color_ribbons:
            continue
        painted = unary_union(color_ribbons).intersection(canvas)
        if painted.is_empty:
            continue
        existing = output.get(color_hex)
        output[color_hex] = (
            painted if existing is None or existing.is_empty
            else unary_union([existing, painted])
        )

    # Free-flow strokes can cross one another after leaving their sampled
    # source regions. Resolve those crossings into one deterministic palette
    # owner so two LightBurn settings never engrave the same positive area.
    output = _exclusive_layers(output, target_colors, canvas)
    minimum_color_run = number(
        settings.get("minimum_color_run_mm"), 0.30, 0, 100
    ) / scale
    minimum_color_area = minimum_color_run * minimum_width
    if callable(logger) and minimum_color_area > 0:
        logger(
            "Structure Tensor Flow: merging color fragments below the "
            "Minimum Color Run threshold."
        )
    output, color_run_transfers = _merge_short_color_runs(
        output, target_colors, minimum_color_area, logger=logger
    )
    if callable(logger):
        logger("Structure Tensor Flow: performing final layer exclusivity check.")
    output = _exclusive_layers(output, target_colors, canvas)
    _assert_exclusive_layers(output)
    if callable(logger):
        logger(
            f"Structure Tensor Flow: flow field complete with "
            f"{len(ribbons)}/{original_ribbon_count} non-overlapping ribbon(s), "
            f"{free_flow_count} free-flow stroke(s), "
            f"{color_run_transfers} short color run(s) merged, "
            f"across {len(output)} color layer(s)."
        )
    return output

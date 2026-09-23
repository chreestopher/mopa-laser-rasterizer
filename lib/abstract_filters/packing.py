"""Small deterministic helpers for optional close-packed geometry layouts."""

import math


class SpatialCollisionIndex:
    """Track nearby geometry without comparing every new item to every item."""

    def __init__(self, bucket_size):
        self.bucket_size = max(float(bucket_size), 1e-9)
        self._buckets = {}

    def _keys(self, bounds):
        min_x, min_y, max_x, max_y = bounds
        start_x = math.floor(min_x / self.bucket_size)
        stop_x = math.floor(max_x / self.bucket_size)
        start_y = math.floor(min_y / self.bucket_size)
        stop_y = math.floor(max_y / self.bucket_size)
        for x_index in range(start_x, stop_x + 1):
            for y_index in range(start_y, stop_y + 1):
                yield x_index, y_index

    def overlaps(self, geometry, tolerance=1e-12):
        seen = set()
        for key in self._keys(geometry.bounds):
            for other in self._buckets.get(key, ()):
                identity = id(other)
                if identity in seen:
                    continue
                seen.add(identity)
                if geometry.intersection(other).area > tolerance:
                    return True
        return False

    def add(self, geometry):
        for key in self._keys(geometry.bounds):
            self._buckets.setdefault(key, []).append(geometry)


def placement_variant(row, column, seed=0):
    """Return a stable integer used for per-item offsets and rotations."""
    return (
        int(row) * 73_856_093
        + int(column) * 19_349_663
        + int(seed) * 83_492_791
    ) & 0x7FFFFFFF


def independent_rotation_degrees(row, column, seed=0):
    """Return one repeatable pseudo-random 0-360 degree item rotation."""
    return (placement_variant(row, column, seed) % 7200) / 20.0

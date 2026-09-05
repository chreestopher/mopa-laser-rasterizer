import math
from shapely.ops import transform
from .common import number, radial_center

DEFAULTS = {"twist": 2.25, "falloff": 1, "center_x": .5, "center_y": .5}
CONTROLS = (("twist", -8, 8, .1), ("falloff", .1, 5, .1), ("center_x", 0, 1, .01), ("center_y", 0, 1, .01))

def apply(geometry, s):
    cx, cy, radius = radial_center(geometry, s)
    twist, falloff = number(s.get("twist"), 2.25, -20, 20)*math.pi, number(s.get("falloff"), 1, .05, 8)
    def warp(x, y, z=None):
        dx, dy = x-cx, y-cy; r = math.hypot(dx, dy); a = math.atan2(dy, dx)+twist*(r/radius)**falloff
        return cx+r*math.cos(a), cy+r*math.sin(a)
    return transform(warp, geometry)

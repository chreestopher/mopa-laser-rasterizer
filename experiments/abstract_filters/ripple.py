import math
from shapely.ops import transform
from .common import number, radial_center

DEFAULTS = {"amplitude": 3, "frequency": .18, "phase": 0, "center_x": .5, "center_y": .5}
CONTROLS = (("amplitude", -30, 30, .5), ("frequency", .01, 1, .01), ("phase", 0, 6.283, .05), ("center_x", 0, 1, .01), ("center_y", 0, 1, .01))

def apply(geometry, s):
    cx, cy, _ = radial_center(geometry, s); amp = number(s.get("amplitude"), 3, -100, 100)
    freq = number(s.get("frequency"), .18, .001, 5); amp = max(-.95/freq, min(.95/freq, amp)); phase = number(s.get("phase"), 0, -100, 100)
    def warp(x, y, z=None):
        dx, dy = x-cx, y-cy; r = math.hypot(dx, dy); ratio = max(0, r+amp*math.sin(r*freq+phase))/r if r else 1
        return cx+dx*ratio, cy+dy*ratio
    return transform(warp, geometry)

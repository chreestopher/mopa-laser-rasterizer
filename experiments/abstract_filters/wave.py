import math
from shapely.ops import transform
from .common import number

DEFAULTS = {"amplitude_x": 4, "amplitude_y": 4, "frequency_x": .1, "frequency_y": .1, "phase": 0}
CONTROLS = (("amplitude_x", -50, 50, .5), ("amplitude_y", -50, 50, .5),
            ("frequency_x", .01, 1, .01), ("frequency_y", .01, 1, .01), ("phase", 0, 6.283, .05))

def apply(geometry, s):
    ax, ay = number(s.get("amplitude_x"), 4, -200, 200), number(s.get("amplitude_y"), 4, -200, 200)
    fx, fy = number(s.get("frequency_x"), .1, .001, 5), number(s.get("frequency_y"), .1, .001, 5)
    ax, ay = max(-.9/fy, min(.9/fy, ax)), max(-.9/fx, min(.9/fx, ay))
    phase = number(s.get("phase"), 0, -100, 100)
    return transform(lambda x, y, z=None: (x + math.sin(y*fy+phase)*ax, y + math.cos(x*fx+phase)*ay), geometry)

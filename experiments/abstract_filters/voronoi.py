import math
import numpy as np
from shapely.geometry import MultiPoint, box
from shapely.ops import voronoi_diagram
from .common import cell_union, number

DEFAULTS = {"cell_size": 15, "jitter": .45, "gap": .8, "seed": 1}
CONTROLS = (("cell_size", 3, 100, 1), ("jitter", 0, .95, .01), ("gap", 0, 12, .1), ("seed", 0, 999999, 1))

def apply(geometry, s):
    bounds = geometry.bounds; step = number(s.get("cell_size"), 15, 3, 500); jitter = number(s.get("jitter"), .45, 0, .95)
    gap = number(s.get("gap"), .8, 0, step*.45); rng = np.random.default_rng(int(number(s.get("seed"), 1, -2147483648, 2147483647)))
    points = [(x*step+rng.uniform(-jitter,jitter)*step, y*step+rng.uniform(-jitter,jitter)*step)
              for x in range(math.floor(bounds[0]/step)-2, math.ceil(bounds[2]/step)+3)
              for y in range(math.floor(bounds[1]/step)-2, math.ceil(bounds[3]/step)+3)]
    cells = voronoi_diagram(MultiPoint(points), envelope=box(*bounds).buffer(step*2)).geoms
    return cell_union(geometry, cells, gap)

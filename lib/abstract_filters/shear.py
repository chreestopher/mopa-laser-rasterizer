from shapely.affinity import affine_transform
from .common import number

DEFAULTS = {"shear_x": .5, "shear_y": 0, "scale_x": 1, "scale_y": .8}
CONTROLS = (("shear_x", -2, 2, .05), ("shear_y", -2, 2, .05), ("scale_x", .25, 3, .05), ("scale_y", .25, 3, .05))

def apply(geometry, s):
    sx, sy = number(s.get("scale_x"), 1, .05, 10), number(s.get("scale_y"), .8, .05, 10)
    shx, shy = number(s.get("shear_x"), .5, -5, 5), number(s.get("shear_y"), 0, -5, 5)
    if abs(sx*sy-shx*shy) < .01: sy += .01
    return affine_transform(geometry, [sx, shx, shy, sy, 0, 0])

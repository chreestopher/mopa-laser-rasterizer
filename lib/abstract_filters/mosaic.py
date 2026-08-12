import math
from shapely.geometry import box
from .common import cell_union, number

DEFAULTS = {"tile_size": 12, "gap": 1, "stagger": .5}
CONTROLS = (("tile_size", 2, 100, 1), ("gap", 0, 20, .1), ("stagger", 0, 1, .05))

def apply(geometry, s):
    x1,y1,x2,y2=geometry.bounds; size=number(s.get("tile_size"),12,2,500); gap=number(s.get("gap"),1,0,size*.8); stagger=number(s.get("stagger"),.5,0,1)
    cells=(box(col*size+(row&1)*stagger*size,row*size,col*size+(row&1)*stagger*size+size,row*size+size)
           for row in range(math.floor(y1/size)-1,math.ceil(y2/size)+2) for col in range(math.floor(x1/size)-2,math.ceil(x2/size)+2))
    return cell_union(geometry,cells,gap)

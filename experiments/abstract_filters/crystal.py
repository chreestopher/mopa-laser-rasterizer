import math
from shapely.geometry import Polygon
from .common import cell_union, number

DEFAULTS = {"cell_size": 18, "gap": .7}
CONTROLS = (("cell_size", 3, 120, 1), ("gap", 0, 20, .1))

def apply(geometry,s):
    x1,y1,x2,y2=geometry.bounds; size=number(s.get("cell_size"),18,3,500); height=size*math.sqrt(3)/2; gap=number(s.get("gap"),.7,0,size*.35); cells=[]
    for row in range(math.floor(y1/height)-2,math.ceil(y2/height)+3):
        for col in range(math.floor(x1/size)-2,math.ceil(x2/size)+3):
            x,y=col*size+(row&1)*size/2,row*height
            cells.extend((Polygon(((x,y),(x+size,y),(x+size/2,y+height))),Polygon(((x,y),(x+size/2,y-height),(x+size,y)))))
    return cell_union(geometry,cells,gap)

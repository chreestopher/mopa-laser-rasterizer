import math
import numpy as np
from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union
from .common import number

DEFAULTS={"recognizability":.65,"glyph_density":.55,"symmetry_order":6,"signal_rings":4,"circuit_branching":.5,"angular_strangeness":.65,"void_ratio":.18,"artifact_age":.15,"signal_seed":1,"core_x":.5,"core_y":.5,"transparent":True,"light_threshold":225}
CONTROLS=(("recognizability",0,1,.05),("glyph_density",0,1,.05),("symmetry_order",1,12,1),("signal_rings",0,12,1),("circuit_branching",0,1,.05),("angular_strangeness",0,1,.05),("void_ratio",0,.6,.02),("artifact_age",0,1,.05),("signal_seed",0,999999,1),("core_x",0,1,.01),("core_y",0,1,.01),("light_threshold",128,255,1))

def apply(geometry,s):
    x1,y1,x2,y2=s.get("_canvas_bounds") or geometry.bounds; width,height=max(x2-x1,1),max(y2-y1,1)
    cx=x1+width*number(s.get("core_x"),.5,0,1); cy=y1+height*number(s.get("core_y"),.5,0,1); radius=math.hypot(width,height)
    recognition=number(s.get("recognizability"),.65,0,1); density=number(s.get("glyph_density"),.55,0,1); rings=int(number(s.get("signal_rings"),4,0,24)); branches=number(s.get("circuit_branching"),.5,0,1); strange=number(s.get("angular_strangeness"),.65,0,1); void=number(s.get("void_ratio"),.18,0,.75); age=number(s.get("artifact_age"),.15,0,1); order=int(number(s.get("symmetry_order"),6,1,24)); rng=np.random.default_rng(int(number(s.get("signal_seed"),1,0,2147483647)))
    cutters=[]; line_width=max(.18,min(width,height)*(.002+void*.018)); spacing=radius*.48/(rings+1) if rings else 0
    for i in range(1,rings+1):
        rr=spacing*i*(1+rng.uniform(-.08,.08)*strange); cutters.append(Point(cx,cy).buffer(rr+line_width).difference(Point(cx,cy).buffer(max(0,rr-line_width))))
    count=max(order,int(order*(1+density*3)))
    for i in range(count):
        angle=2*math.pi*i/count+rng.uniform(-1,1)*strange*math.pi/max(order,1); start=radius*rng.uniform(.03,.28); end=radius*rng.uniform(.35,.72)*(.5+branches*.5)
        p1=(cx+math.cos(angle)*start,cy+math.sin(angle)*start); p2=(cx+math.cos(angle)*end,cy+math.sin(angle)*end)
        cutters.append(LineString((p1,p2)).buffer(line_width,cap_style=2))
        if rng.random()<density: cutters.append(Point(*p2).buffer(line_width*rng.uniform(1.5,4)))
    cutter=unary_union(cutters) if cutters else geometry.intersection(box(0,0,0,0)); carved=geometry.difference(cutter)
    if recognition>.85: carved=unary_union((carved,geometry.intersection(cutter).buffer(-line_width*recognition)))
    if age:
        erosion=line_width*age*.75; carved=carved.buffer(-erosion).buffer(erosion)
    return carved

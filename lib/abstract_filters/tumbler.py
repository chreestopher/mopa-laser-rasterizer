import math
from shapely.ops import transform
from .common import number

DEFAULTS = {"top_diameter_mm":75,"middle_diameter_mm":75,"bottom_diameter_mm":70,"artwork_height_mm":100,"wrap_angle":180,"profile_curve":0,"horizontal_anchor":.5,"material":"metal","powdercoat_gap_mm":.35,"powdercoat_simplification_mm":.3,"foreground_min_percent":.15}
CONTROLS = (("top_diameter_mm",20,200,.1),("middle_diameter_mm",20,200,.1),("bottom_diameter_mm",20,200,.1),("artwork_height_mm",5,300,1),("wrap_angle",10,360,1),("profile_curve",-1,1,.05),("horizontal_anchor",0,1,.05),("powdercoat_gap_mm",0,3,.05),("powdercoat_simplification_mm",0,3,.05),("foreground_min_percent",0,5,.05))

def apply(geometry,s):
    x1,y1,x2,y2=s.get("_canvas_bounds") or geometry.bounds; sw,sh=max(x2-x1,1e-9),max(y2-y1,1e-9); pixel=number(s.get("_scale_factor"),1,.0001,1000)
    top,mid,bot=(number(s.get(k),d,1,1000) for k,d in (("top_diameter_mm",75),("middle_diameter_mm",75),("bottom_diameter_mm",70)))
    hmm=number(s.get("artwork_height_mm"),sh*pixel,.1,5000); fraction=number(s.get("wrap_angle"),180,1,360)/360; curve=number(s.get("profile_curve"),0,-1,1); anchor=number(s.get("horizontal_anchor"),.5,0,1)
    def diameter(t):
        d=top+(mid-top)*t*2 if t<=.5 else mid+(bot-mid)*(t-.5)*2
        return max(1,d+curve*min(top,mid,bot)*.12*math.sin(math.pi*t))
    maximum=math.pi*max(top,mid,bot)*(1+max(0,curve)*.12)*fraction/pixel
    def unwrap(x,y,z=None):
        t=min(1,max(0,(y-y1)/sh)); target=math.pi*diameter(t)*fraction/pixel
        return x1+anchor*(maximum-target)+(x-x1)/sw*target,y1+t*hmm/pixel
    return transform(unwrap,geometry)

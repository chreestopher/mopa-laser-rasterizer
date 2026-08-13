from . import centerline, crystal, glitch, mosaic, ripple, shattered, shear, spiral, voronoi, wave

MODULES={
    "wave":wave,"voronoi":voronoi,"shear":shear,"spiral":spiral,
    "mosaic":mosaic,"crystal":crystal,"ripple":ripple,
    "centerline":centerline,"glitch":glitch,"shattered":shattered,
}
ALIASES={"tessellation":"crystal","triangles":"crystal","topographic":"ripple","xenoglyph":"shattered","alien":"shattered"}
FULL_PALETTE_FILTERS={"wave","voronoi","shear","spiral","mosaic","crystal","ripple","glitch","shattered"}

def canonical_name(name):
    name=str(name or "none").strip().lower()
    return ALIASES.get(name,name)

def settings(name,supplied=None):
    name=canonical_name(name); values=dict(getattr(MODULES.get(name),"DEFAULTS",{})); values.update(supplied or {})
    return name,values

def apply(name,geometry,values):
    module=MODULES.get(canonical_name(name)); return module.apply(geometry,values) if module and hasattr(module,"apply") else geometry

def manifest():
    return {name:{"defaults":dict(module.DEFAULTS),"controls":[dict(name=n,min=lo,max=hi,step=step) for n,lo,hi,step in module.CONTROLS]} for name,module in MODULES.items()}

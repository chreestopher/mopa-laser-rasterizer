from . import centerline, crystal, mosaic, ripple, shear, spiral, tumbler, voronoi, wave, xenoglyph

MODULES={
    "wave":wave,"voronoi":voronoi,"shear":shear,"spiral":spiral,
    "mosaic":mosaic,"crystal":crystal,"ripple":ripple,
    "centerline":centerline,"tumbler":tumbler,"xenoglyph":xenoglyph,
}
ALIASES={"tessellation":"crystal","triangles":"crystal","topographic":"ripple","alien":"xenoglyph"}
FULL_PALETTE_FILTERS={"wave","voronoi","shear","spiral","mosaic","crystal","ripple","xenoglyph"}

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

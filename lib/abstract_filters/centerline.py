DEFAULTS={"line_simplification":.35,"min_branch_length":2}
CONTROLS=(("line_simplification",0,3,.05),("min_branch_length",0,30,1))

# Centerline consumes raster boxes rather than finalized polygon geometry.
# The shared pipeline invokes this processor before welding.
def process_boxes(boxes, settings, skeletonizer):
    return skeletonizer(boxes, settings)

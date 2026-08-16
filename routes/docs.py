"""Public, crawlable product documentation and practical user guides."""

from flask import Response, current_app, render_template, request

from . import routes


def _page(title, description, intro, sections, related=()):
    return {
        "title": title, "description": description, "intro": intro,
        "sections": sections, "related": list(related),
    }


DOCS = {
    "raster-to-vector": _page(
        "Raster Images to LightBurn Vector Projects",
        "How MOPA Laser Rasterizer converts bitmap artwork into color-separated SVG and LightBurn vector geometry.",
        "The Rasterizer turns a JPG or PNG into closed vector regions, assigns those regions to LightBurn palette layers, and exports an SVG and an LBRN2 project.",
        [
            ("What the conversion does", ["The image is resized, reduced to the selected palette, grouped into color regions, cleaned, and written as vector geometry. Each exported color must have a matching usable setting in the selected LightBurn Material Library."]),
            ("What to prepare", ["Use a readable JPG or PNG, choose a physical pixel size, and select only colors backed by settings you intend to engrave. A cleaner source image usually produces fewer vector objects and a smaller LightBurn project."]),
            ("What the export preserves", ["The output preserves the processed color regions rather than the original bitmap pixels. It is intended to be editable and layer-addressable in LightBurn; it is not a lossless reconstruction of the source photograph."]),
        ], ["image-presets", "color-layers", "lightburn-export", "pixel-size"]),
    "image-presets": _page(
        "Choosing an Image Processing Preset",
        "Compare Cartoon, Color Photo, Black and White Photo, and abstract vector presets before exporting to LightBurn.",
        "Presets control how source pixels become color regions. Choose according to the artwork and the type of geometry you want to edit or engrave.",
        [
            ("Cartoon", ["Best for logos, illustrations, and artwork with deliberate flat colors. It favors clear regions and readable boundaries."]),
            ("Color Photo", ["Designed for photographs where several palette colors are needed to retain visual structure. Results depend strongly on palette choice and processing resolution."]),
            ("Black and White Photo", ["Reduces the image to dark and light marks using a dithered photographic treatment. It is useful when a single engraving layer must suggest tonal detail."]),
            ("Abstract styles", ["Abstract presets deliberately transform geometry. They are creative effects, not faithful photo conversions, and each exposes controls specific to its structure."]),
        ], ["cartoon-preset", "color-photo-preset", "black-and-white-photo", "abstract-filters"]),
    "cartoon-preset": _page(
        "Cartoon Raster-to-Vector Preset",
        "Use the Cartoon preset to convert logos, illustrations, and flat-color artwork into clean LightBurn color regions.",
        "Cartoon is the general-purpose preset for artwork whose shapes and color boundaries matter more than photographic texture.",
        [("Good source artwork", ["Use high-contrast illustrations, logos, clip art, or simplified renders. Small isolated details may be removed by cleanup settings."]), ("Palette selection", ["Select enough swatches to represent the artwork without creating unnecessary layers. Every enabled output color should correspond to a Material Library setting."]), ("When to choose another preset", ["Use Color Photo for continuous-tone imagery and Black and White Photo for a one-color photographic engraving pattern."])],
        ["raster-to-vector", "color-layers", "material-libraries"]),
    "color-photo-preset": _page(
        "Color Photograph to Layered LightBurn Vectors",
        "Convert a color photograph into palette-matched vector regions for layered MOPA laser processing in LightBurn.",
        "Color Photo maps photographic colors to the enabled LightBurn palette and builds vector regions for those mapped colors.",
        [("Expect simplification", ["A photograph contains far more colors than a practical laser project. The preset reduces those colors and may merge or omit subtle transitions."]), ("Control project complexity", ["Processing more pixels and enabling more colors can increase object count, memory use, and LightBurn file size. Start at the lowest resolution that retains the important subject detail."]), ("Material settings", ["Color appearance on metal depends on the laser, lens, focus, material, preparation, and settings. The app applies library settings; it cannot guarantee that a screen color will match an engraved color."])],
        ["pixel-size", "color-layers", "reduce-lightburn-object-count", "material-libraries"]),
    "black-and-white-photo": _page(
        "Black and White Photo Engraving Vectors",
        "Prepare a photograph as dark dithered geometry for a single-layer LightBurn engraving project.",
        "The Black and White Photo preset represents tone with dark marks rather than multiple color layers.",
        [("How tone is represented", ["The source is reduced to dark and light decisions. The spacing and distribution of dark geometry create the impression of intermediate tone at viewing distance."]), ("Source-image tips", ["Images with a clear subject, controlled background, and useful contrast generally translate better than low-contrast or heavily compressed images."]), ("Test before production", ["Run a small material test because dot size, heat accumulation, focus, and surface finish change the apparent darkness."])],
        ["image-presets", "pixel-size", "lightburn-export"]),
    "abstract-filters": _page(
        "Abstract Raster-to-Vector Filters",
        "Guide to Wave, Voronoi, Shear, Spiral, Mosaic, Crystal, Ripple, Centerline, Glitch, Deep Fryer, and Shattered presets.",
        "Abstract filters transform coalesced image geometry into intentionally stylized vector structures before export.",
        [("Geometry-first effects", ["Most filters operate on vector regions created from the selected palette. Their controls change the structure while the normal Material Library and LightBurn export rules still apply."]), ("Performance", ["Dense source images and aggressive settings can create many shapes. Use the job console to follow each layer and reduce processing dimensions when exploring settings."]), ("Available styles", ["Wave Flow, Voronoi, Shear, Spiral Vortex, Staggered Mosaic, Crystal Tessellation, Topographic Ripple, Centerline Drawing, Digital Glitch, Deep Fryer, and Shattered are documented individually below."])],
        ["wave-filter", "voronoi-filter", "centerline-filter", "abstract-filter-reference"]),
    "abstract-filter-reference": _page(
        "Abstract Filter Selection Reference",
        "A concise reference for selecting an abstract geometry style for laser-ready vector artwork.",
        "Choose a filter by the visual structure you want, then test its controls on a reduced-size job before producing a full-resolution project.",
        [("Flow and direction", ["Wave Flow, Shear, Spiral Vortex, and Topographic Ripple emphasize directional movement."]), ("Cells and fragments", ["Voronoi, Staggered Mosaic, Crystal Tessellation, and Shattered divide regions into repeated or fractured structures."]), ("Line and digital treatments", ["Centerline Drawing favors stroke-like structure; Digital Glitch and Deep Fryer produce deliberately harsher synthetic treatments."])],
        ["abstract-filters", "reduce-lightburn-object-count"]),
    "material-vault": _page(
        "LightBurn Material Vault",
        "Save, inspect, edit, combine, and reuse LightBurn Material Library files with an authenticated account.",
        "The Material Vault is the account-backed home for LightBurn libraries and Holographic Recipes used by the Rasterizer and Holographic Lab.",
        [("Saved libraries", ["Signed-in users can upload supported LightBurn library files, inspect entries, edit metadata and settings, create libraries, and build a new library from selected entries."]), ("Shared source", ["The Rasterizer and Holographic Lab select from the same saved Material Library source. Guest users instead retain supported selections for the current browser session."]), ("Holographic Recipes", ["Recipe JSON files are stored separately beneath Material Libraries because a measured recipe is not itself a LightBurn Material Library."])],
        ["material-libraries", "holographic-recipes", "color-layers"]),
    "material-libraries": _page(
        "Using LightBurn Material Libraries",
        "How material names, setting descriptions, layer colors, and laser parameters are resolved during LightBurn export.",
        "A Material Library supplies the actual LightBurn cut settings attached to exported layers.",
        [("Matching", ["Rasterizer layers are associated with recognized palette descriptions. Holographic calibration additionally uses the selected material name and setting Description to find its base setting."]), ("Sublayers", ["Where a matched setting contains sublayers, the workflow may use the applicable base or first sublayer according to the feature. Review the resulting LightBurn project before running it."]), ("Machine-specific data", ["Speed, power, frequency, pulse width, passes, scan interval, and cut mode are machine- and material-dependent. Treat imported settings as starting data that requires validation on your equipment."])],
        ["material-vault", "color-layers", "holographic-calibration"]),
    "color-layers": _page(
        "Color Separation and LightBurn Layers",
        "Understand how image colors become LightBurn palette layers and why unmatched colors may not export.",
        "The app uses the LightBurn palette as a stable bridge between processed image color and project-layer settings.",
        [("Selected swatches", ["Enabled swatches define the available target colors. Pixels are assigned to suitable colors during processing, then same-color geometry is grouped for export."]), ("Layer settings", ["A layer needs matching Material Library data to be useful. If a chosen color has no matching setting, the pipeline may omit that color rather than fabricate unsafe laser parameters."]), ("Color is not a guarantee", ["Palette color identifies a layer and intended recipe; it does not guarantee the physical color produced by a laser-marking process."])],
        ["material-libraries", "color-photo-preset", "lightburn-export"]),
    "pixel-size": _page(
        "Choosing Physical Pixel Size for Laser Vectorization",
        "How physical pixel size and processing dimensions affect detail, object count, engraving scale, and LightBurn performance.",
        "Physical pixel size connects processed image pixels to millimeters in the exported project.",
        [("Smaller pixels", ["Smaller values can retain finer structure but may increase geometry count and demand more from the worker, LightBurn, and the laser process."]), ("Larger pixels", ["Larger values simplify the result and enlarge each processed unit. They can improve robustness but may visibly reduce detail."]), ("Practical workflow", ["Begin with a modest processing dimension, inspect the result at its intended physical size, and increase resolution only when missing detail matters."])],
        ["reduce-lightburn-object-count", "raster-to-vector", "holographic-artwork"]),
    "reduce-lightburn-object-count": _page(
        "Reduce LightBurn Vector Object Count",
        "Ways to make raster-to-vector and holographic LightBurn projects smaller without blindly changing laser settings.",
        "Large projects usually come from high processing resolution, complex boundaries, many colors, or geometry that cannot be coalesced into larger regions.",
        [("Start with resolution", ["Lower processing width or height first. This reduces the number of source cells before expensive geometry work begins."]), ("Limit palette complexity", ["Use only colors that contribute meaningfully to the image. More color boundaries commonly mean more separate shapes."]), ("Choose the right source", ["Clean edges, reduced noise, and simplified backgrounds generally coalesce better than compressed or highly textured imagery."]), ("Watch the logs", ["The job console reports source pixels, per-layer counts, coalescing, serialization, and completion so you can identify which stage expands the project."])],
        ["pixel-size", "job-history", "image-presets"]),
    "lightburn-export": _page(
        "SVG and LightBurn LBRN2 Export",
        "What is included in Rasterizer SVG and LBRN2 downloads and what to verify before running a laser job.",
        "Completed jobs provide vector SVG and LightBurn project downloads. The LBRN2 version carries layer assignments and matched settings.",
        [("Before engraving", ["Open the project in LightBurn and verify size, origin, layer order, cut mode, speed, power, frequency, pulse width, passes, and scan interval."]), ("SVG versus LBRN2", ["SVG is portable vector geometry. LBRN2 is intended to preserve the LightBurn-specific project and layer configuration."]), ("Safety", ["Never treat generated settings as automatically safe. Confirm your machine limits, material compatibility, ventilation, focus, and fire-control procedures."])],
        ["works-with-lightburn", "job-history", "material-libraries", "color-layers"]),
    "works-with-lightburn": _page(
        "Designed to Work with LightBurn",
        "MOPA Laser Rasterizer complements LightBurn by preparing vector artwork, color layers, and settings; it does not replace laser-control software.",
        "MOPA Laser Rasterizer is an artwork-preparation assistant for LightBurn. It handles specialized raster-to-vector, material-library, and diffraction-calibration work, then hands the resulting project to LightBurn for inspection and production.",
        [
            ("LightBurn remains the production workspace", ["LightBurn is established laser software with the device setup, layout, editing, layer controls, framing, and machine-operation workflow operators rely on. This application does not attempt to reproduce or replace those capabilities."]),
            ("What this application adds", ["The Rasterizer prepares color-separated vector geometry from images, associates layers with settings from a LightBurn Material Library, and exports an editable LBRN2 project. The Holographic Etching Lab adds a calibration-first way to prepare experimental diffraction artwork for that same LightBurn workflow."]),
            ("The handoff is intentional", ["Generated SVG and LBRN2 files are starting points for review in LightBurn. Before running a laser, use LightBurn to confirm project dimensions, placement, device selection, layer order, cut mode, speed, power, frequency, pulse width, passes, interval, and scan direction."]),
            ("A companion, not a controller", ["This application does not connect to or command the laser. It does not frame a job, configure a device, replace machine safety controls, or decide that settings are safe. The operator remains responsible for the final LightBurn project and physical process."]),
        ], ["lightburn-export", "material-libraries", "raster-to-vector", "holographic-etching"]),
    "job-history": _page(
        "Processing Logs, Queue Position, and Job History",
        "Track Rasterizer and Holographic Artwork jobs, inspect batched processing logs, and download retained outputs.",
        "The shared processing console distinguishes a queued job from a stalled one and keeps retained outputs together.",
        [("Queue and processing", ["Pending jobs show their queue position. Once claimed by a dedicated worker, staged logs describe the current operation and processed-object counts."]), ("Account and guest history", ["Authenticated history is tied to the account. Guest history is tied to the browser session and is not intended as permanent storage."]), ("Downloads", ["SVG and LBRN2 actions become available after successful completion. Download important work rather than relying indefinitely on retained server artifacts."])],
        ["raster-to-vector", "holographic-artwork", "reduce-lightburn-object-count"]),
    "holographic-etching": _page(
        "Holographic Etching Lab for MOPA Lasers",
        "An experimental calibration-first workflow for diffraction-grating artwork and structural color on suitable laser-marked surfaces.",
        "The Holographic Etching Lab generates a test grid, analyzes a photograph of the engraved result, saves measured recipes, and maps artwork colors to those recipes.",
        [("The workflow", ["Generate and engrave a calibration grid; photograph it under a controlled viewing and lighting setup; analyze and review measured cells; save useful recipes; then build Holographic Artwork."]), ("Why calibration is necessary", ["Diffraction appearance depends on grating geometry, scan direction, laser parameters, surface, lighting, and viewing angle. A recipe measured in one setup may not reproduce identically in another."]), ("Experimental status", ["This feature prepares geometry and settings for testing. It does not promise a particular physical color or certify a laser process."])],
        ["holographic-calibration", "analyze-calibration-photo", "holographic-recipes", "holographic-artwork"]),
    "holographic-calibration": _page(
        "Generate a Holographic Diffraction Calibration Grid",
        "Create a labeled LightBurn calibration grid that varies scan interval, angle, and an optional MOPA setting sweep.",
        "The calibration grid creates known cells whose requested parameters can later be paired with colors observed in a photograph.",
        [("Rows and columns", ["Columns span the configured interval range, while rows span scan angles. The saved profile records the grid dimensions and each cell’s requested parameters."]), ("Cut mode override", ["Setting uses the matched Material Library cut type. Line, Fill, or Offset Fill overrides the exported calibration layers when explicitly selected."]), ("Identification and alignment", ["The engraved grid includes labels, fiducials, and its calibration identifier so the physical test can be associated with the correct profile."])],
        ["choose-cut-mode", "analyze-calibration-photo", "material-libraries"]),
    "analyze-calibration-photo": _page(
        "Photograph and Analyze a Holographic Calibration Grid",
        "How to capture, align, crop, and sample a diffraction calibration grid to build measured color recipes.",
        "Analysis uses the saved calibration profile to know the expected rows, columns, cell parameters, and grid identity.",
        [("Photography", ["Keep the material flat, use stable illumination and viewing geometry, avoid clipped highlights, and include the complete border and fiducials when possible."]), ("Alignment tools", ["Automatic rectification can be supplemented with rotation, crop controls, manual corners, and manual sample points when the grid is not confidently detected."]), ("Review before saving", ["Observed color, confidence, quality flags, and recipe similarity diagnostics help identify weak or redundant cells. Keep only measurements you trust."])],
        ["holographic-calibration", "holographic-recipes", "diffraction-gratings"]),
    "holographic-recipes": _page(
        "Holographic Etching Recipes",
        "What a Holographic Recipe JSON file contains and how it relates to a LightBurn Material Library.",
        "A Holographic Recipe records measured color observations and the calibration parameters associated with selected grid cells.",
        [("Recipe versus Material Library", ["The recipe is JSON measurement data. The Material Library is a LightBurn settings file. The recipe references the material and base setting used during calibration, but the two file types serve different purposes."]), ("Saved recipes", ["Signed-in users can retain recipe files in the Material Vault area. Guest workflows can remember a recent recipe for the current browser session."]), ("Reuse limits", ["Recipes are specific to the conditions under which they were measured. Recalibrate when the laser, lens, focus, substrate, preparation, or optical setup changes materially."])],
        ["material-vault", "holographic-calibration", "holographic-artwork"]),
    "holographic-artwork": _page(
        "Convert Artwork into Holographic Diffraction Layers",
        "Map artwork pixels to measured Holographic Recipes and export closed rectangles on calibrated LightBurn layers.",
        "Holographic Artwork assigns each processed pixel to the nearest measured recipe color, coalesces adjacent pixels, and exports the result using recipe-specific scan intervals and angles.",
        [("Inputs", ["Choose ordinary artwork, a saved or uploaded Holographic Recipe, and the existing Material Library used by that recipe."]), ("Layer generation", ["Each measured recipe receives its own LightBurn layer and angle. Adjacent same-recipe pixels are merged into non-overlapping closed rectangles to reduce object count."]), ("Black outlines and cut mode", ["Optional black geometry uses the matching black Material Library setting. Cut mode can use the setting as stored or be overridden with Line, Fill, or Offset Fill."]), ("Job processing", ["Artwork exports run on the dedicated worker and redirect to the shared job console for queue position, staged logs, and downloads."])],
        ["holographic-recipes", "choose-cut-mode", "reduce-lightburn-object-count", "job-history"]),
    "diffraction-gratings": _page(
        "Laser Diffraction Gratings and Structural Color",
        "Practical background on why fine directional laser patterns can produce angle-dependent color and why calibration matters.",
        "Closely spaced directional structures can diffract light, producing an appearance that changes with illumination and viewing direction.",
        [("Direction matters", ["Rotating a grating changes the direction in which diffracted light is sent. That is why scan angle is recorded as part of each measured recipe."]), ("Spacing matters", ["The effective structure depends on scan interval and on the marks produced by the selected laser parameters. Requested spacing is not the same as a guaranteed physical groove profile."]), ("Measurement matters", ["A camera records one lighting and viewing arrangement. Treat sampled RGB values as a lookup for that setup, not a universal material color specification."])],
        ["holographic-etching", "holographic-calibration", "analyze-calibration-photo"]),
    "choose-cut-mode": _page(
        "Line, Fill, Offset Fill, or Material Setting",
        "How to choose a LightBurn cut-mode override for holographic calibration grids and artwork exports.",
        "The cut-mode selector controls the exported LightBurn layer type; it does not replace the remaining laser parameters in the matched setting.",
        [("Setting", ["Uses the cut type already stored in the selected Material Library setting. This is the default and the safest choice when the library is intentionally configured."]), ("Line", ["Uses LightBurn’s line-style cut mode. Closed rectangle boundaries are processed as paths rather than conventional scan fills."]), ("Fill", ["Uses a scan fill, where interval and angle are directly relevant to the hatch pattern."]), ("Offset Fill", ["Uses LightBurn’s offset-fill type. Confirm how your LightBurn version interprets interval and direction for the generated closed geometry."])],
        ["holographic-calibration", "holographic-artwork", "material-libraries"]),
    "mopa-laser-workflow": _page(
        "MOPA Laser Artwork Workflow",
        "A cautious workflow for moving from image preparation and LightBurn settings to material tests and final laser marking.",
        "The app prepares projects; successful physical results still require machine-specific testing and operator judgment.",
        [("Prepare", ["Use known material, clean artwork, a reviewed Material Library, and processing dimensions appropriate to the final size."]), ("Inspect", ["Open every generated project in LightBurn and verify geometry, bounds, layers, device assignment, and all laser parameters."]), ("Test", ["Run small coupons before valuable work. Observe heat accumulation, warping, smoke, color consistency, and whether the result remains within machine and material limits."]), ("Operate safely", ["Use suitable extraction, guarding, eye protection, supervision, and fire precautions. Follow the laser manufacturer and material supplier guidance."])],
        ["works-with-lightburn", "material-libraries", "lightburn-export", "holographic-etching"]),
    "troubleshooting": _page(
        "Rasterizer and Holographic Lab Troubleshooting",
        "Diagnose queued jobs, missing layers, large LightBurn files, unmatched settings, and calibration-photo problems.",
        "Start with the job log: it identifies the active operation, color or layer, processed count, and terminal failure when one is available.",
        [("A job appears stuck", ["Check whether its state is pending or processing. Pending jobs report queue position; processing jobs should emit batched stage logs. A worker restart or memory termination will appear in infrastructure logs and should produce a failed or recovered queue state."]), ("A color layer is missing", ["Confirm the swatch was enabled and has a matching Material Library entry. Also inspect whether preprocessing merged the color into a nearer enabled swatch."]), ("The project is too large", ["Reduce processing dimensions, palette count, or source-image noise. Review per-layer object counts to find the main contributor."]), ("Calibration analysis is weak", ["Retake the photograph with the full grid visible, stable lighting, sharper focus, and less glare; then use manual alignment or sample controls where necessary."])],
        ["job-history", "color-layers", "reduce-lightburn-object-count", "analyze-calibration-photo"]),
}


FILTER_PAGES = {
    "wave": ("Wave Flow", "warps regions into flowing directional bands"),
    "voronoi": ("Voronoi", "divides regions into cell-like geometric territories"),
    "shear": ("Shear", "offsets geometry into a slanted directional treatment"),
    "spiral": ("Spiral Vortex", "rotates geometry around a vortex-like field"),
    "mosaic": ("Staggered Mosaic", "rebuilds regions as offset tile-like blocks"),
    "crystal": ("Crystal Tessellation", "facets regions into crystalline polygonal structure"),
    "ripple": ("Topographic Ripple", "introduces repeated contour-like displacement"),
    "centerline": ("Centerline Drawing", "reduces suitable regions toward stroke-like center structures"),
    "glitch": ("Digital Glitch", "applies deliberate block displacement and digital interruption"),
    "deep-fryer": ("Deep Fryer", "pushes geometry toward an aggressive high-contrast synthetic treatment"),
    "shattered": ("Shattered", "fragments regions into a broken angular composition"),
}
for slug, (name, behavior) in FILTER_PAGES.items():
    DOCS[f"{slug}-filter"] = _page(
        f"{name} Abstract Vector Filter",
        f"Use the {name} preset to transform raster-derived color regions into laser-ready abstract vector geometry.",
        f"{name} is an optional creative preset that {behavior}. It operates within the normal palette, Material Library, job logging, and LightBurn export workflow.",
        [("Best use", ["Start with a recognizable subject or strong color silhouette. The effect is intentionally interpretive, so test a small processing size before committing to a detailed export."]), ("Controls", ["The preset panel exposes only the parameters supported by this filter. Larger or denser values can increase processing time and object count depending on the source geometry."]), ("Output", ["The transformed regions remain assigned to their applicable color layers and Material Library settings. Inspect the final SVG and LBRN2 project before engraving."])],
        ["abstract-filters", "abstract-filter-reference", "reduce-lightburn-object-count"],
    )


DOC_GROUPS = [
    ("Rasterizer", ["raster-to-vector", "image-presets", "cartoon-preset", "color-photo-preset", "black-and-white-photo", "pixel-size", "color-layers"]),
    ("Abstract filters", ["abstract-filters", "abstract-filter-reference"] + [f"{slug}-filter" for slug in FILTER_PAGES]),
    ("LightBurn and materials", ["works-with-lightburn", "material-vault", "material-libraries", "lightburn-export", "reduce-lightburn-object-count", "mopa-laser-workflow"]),
    ("Holographic Etching Lab", ["holographic-etching", "holographic-calibration", "analyze-calibration-photo", "holographic-recipes", "holographic-artwork", "diffraction-gratings", "choose-cut-mode"]),
    ("Jobs and support", ["job-history", "troubleshooting"]),
]


@routes.route("/docs")
def docs_index():
    return render_template("docs.html", page=None, pages=DOCS, groups=DOC_GROUPS,
                           canonical=_canonical("/docs"))


@routes.route("/docs/<slug>")
def docs_page(slug):
    page = DOCS.get(slug)
    if not page:
        return render_template("docs.html", page=None, pages=DOCS, groups=DOC_GROUPS,
                               canonical=_canonical("/docs")), 404
    return render_template("docs.html", page=page, slug=slug, pages=DOCS, groups=DOC_GROUPS,
                           canonical=_canonical(f"/docs/{slug}"))


def _canonical(path):
    base = current_app.config.get("PUBLIC_APP_URL") or request.url_root.rstrip("/")
    return f"{base}{path}"


@routes.route("/sitemap.xml")
def sitemap():
    paths = ["/", "/holographic-etching", "/material-libraries", "/docs"]
    paths.extend(f"/docs/{slug}" for slug in DOCS)
    body = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    body += "\n".join(f"  <url><loc>{_canonical(path)}</loc></url>" for path in paths)
    body += "\n</urlset>\n"
    return Response(body, mimetype="application/xml")


@routes.route("/robots.txt")
def robots():
    return Response(f"User-agent: *\nAllow: /\nSitemap: {_canonical('/sitemap.xml')}\n",
                    mimetype="text/plain")

"""Public, crawlable product documentation and practical user guides."""

from flask import Response, current_app, render_template, request
from lib.abstract_filters import manifest as abstract_filter_manifest

from . import routes


def _page(title, description, intro, sections, related=()):
    return {
        "title": title, "description": description, "intro": intro,
        "sections": sections, "related": list(related),
    }


DOCS = {
    "preset-controls": _page(
        "Understanding Rasterizer Preset Controls",
        "A practical reference for artwork size, physical pixel size, palette, Material Library, presets, and abstract-filter controls.",
        "Think of the Rasterizer as a workshop with three stations: image resolution chooses how much raw detail enters, the palette sorts that detail into bins, and the preset determines how each bin is shaped before LightBurn receives it.",
        [
            ("Processing width and height", ["These dimensions are like the pixel dimensions of a digital camera: more pixels can record more detail, but they also create more material for the geometry pipeline to inspect. Leaving one dimension automatic preserves the source aspect ratio while the specified dimension sets the scale of processing."]),
            ("Physical pixel size", ["This is comparable to graph-paper square size. A processed cell represents that many millimeters in the export. Smaller squares can describe finer detail; larger squares make a coarser, often simpler physical result."]),
            ("Palette swatches", ["The palette works like sorting mixed hardware into labeled drawers. Every source pixel is directed toward an enabled color drawer, and that drawer needs a matching Material Library setting for a useful LightBurn layer."]),
            ("Preset", ["A preset is like choosing a tool head before working the material. Cartoon, Color Photo, and Black and White Photo organize the source differently; abstract filters reshape the resulting geometry intentionally."]),
            ("Material and Material Library", ["The material name selects the relevant shelf, while setting descriptions identify the recipes placed on exported layers. These settings are production data, not merely visual labels, and must be reviewed in LightBurn."]),
        ], ["image-presets", "pixel-size", "color-layers", "abstract-filter-reference"]),
    "raster-to-vector": _page(
        "Raster Images to LightBurn Vector Projects",
        "How MOPA Laser Rasterizer converts bitmap artwork into color-separated SVG and LightBurn vector geometry.",
        "The Rasterizer turns a JPG or PNG into closed vector regions, assigns those regions to LightBurn palette layers, and exports an SVG and an LBRN2 project.",
        [
            ("What the conversion does", ["The image is resized, reduced to the selected palette, grouped into color regions, cleaned, and written as vector geometry. Each exported color must have a matching usable setting in the selected LightBurn Material Library."]),
            ("What to prepare", ["Use a readable JPG or PNG, choose a physical pixel size, and select only colors backed by settings you intend to engrave. A cleaner source image usually produces fewer vector objects and a smaller LightBurn project."]),
            ("What the export preserves", ["The output preserves the processed color regions rather than the original bitmap pixels. It is intended to be editable and layer-addressable in LightBurn; it is not a lossless reconstruction of the source photograph."]),
        ], ["image-presets", "color-layers", "lightburn-export", "pixel-size"]),
    "raster-vs-vector": _page(
        "Raster Graphics, Vector Graphics, and Laser Artwork",
        "Why MOPA Laser Rasterizer is also a vectorizer, how pixels differ from paths, and what each representation contributes to a LightBurn workflow.",
        "The name Rasterizer describes where the workflow begins: with raster artwork made from pixels. The result, however, is largely vector geometry. In that sense the application is also a specialized vectorizer—one that uses palette colors, presets, and Material Library settings to decide how pixels should become closed shapes and LightBurn layers.",
        [
            ("What is a raster graphic?", ["A raster image is a rectangular grid of pixels. JPG, PNG, photographs, screenshots, and digital paintings are common raster sources. Each pixel records a color at one location, much like one square on a sheet of colored graph paper.", "Raster artwork is excellent for photographs, texture, soft shading, and direct image editing. Its main limitation is resolution: enlarging it eventually reveals pixels, and converting millions of individual color decisions into editable laser shapes can require substantial processing."]),
            ("What is a vector graphic?", ["A vector graphic describes geometry with points, lines, curves, and closed shapes rather than a fixed pixel grid. SVG and much of the editable geometry inside a LightBurn project are vector representations.", "Vectors can be resized without revealing source pixels, are convenient for editing outlines and regions, and can carry clear layer assignments. Their challenge is complexity: a detailed photograph converted too literally may become thousands of shapes or control points, creating a file that is mathematically scalable but still slow to edit or process."]),
            ("Why laser workflows use both", ["Raster engraving can scan an image line by line and is a natural fit for photographs or continuous tone. Vector operations follow paths or fill defined shapes and are a natural fit for outlines, logos, cut boundaries, and layer-specific settings.", "Neither representation is universally better. Raster data is compact and expressive for pixel-based tone; vector data is explicit and editable for geometry. The appropriate choice depends on the desired mark, machine process, material, and how much control the operator needs over individual regions."]),
            ("What this application converts", ["The Rasterizer reads source pixels, resizes them, and maps them to enabled palette colors. It then joins neighboring same-color cells into closed regions, cleans or transforms those regions according to the preset, removes unwanted overlap, and writes vector SVG and LBRN2 output.", "This is not general-purpose automatic tracing. The conversion is specifically organized around color-separated laser artwork and matching LightBurn Material Library settings."]),
            ("Benefits for laser preparation", ["The vector result gives each processed color an identifiable layer, permits region-level inspection in LightBurn, and avoids requiring the operator to trace and sort every color manually. Closed geometry also supports fill-oriented workflows and controlled punch-through between color regions."]),
            ("Challenges and tradeoffs", ["More source pixels can preserve detail but increase classification and geometry work. More colors create more boundaries and layers. Strong simplification can make the project easier to handle but remove detail; insufficient simplification can preserve noise and create excessive objects.", "A vector file is not automatically a better laser job. Always inspect scale, object count, closed paths, layer order, fill behavior, and laser settings in LightBurn, then test the intended process on the actual material."]),
        ], ["raster-to-vector", "pixel-size", "reduce-lightburn-object-count", "lightburn-export", "works-with-lightburn"]),
    "image-presets": _page(
        "Choosing an Image Processing Preset",
        "Compare Cartoon, Color Photo, Black and White Photo, and abstract vector presets before exporting to LightBurn.",
        "Presets control how source pixels become color regions. Choose according to the artwork and the type of geometry you want to edit or engrave.",
        [
            ("Cartoon", ["Best for logos, illustrations, and artwork with deliberate flat colors. It favors clear regions and readable boundaries."]),
            ("Color Photo", ["Designed for photographs where several palette colors are needed to retain visual structure. Results depend strongly on palette choice and processing resolution."]),
            ("Black and White Photo", ["Reduces the image to dark and light marks using a dithered photographic treatment. It is useful when a single engraving layer must suggest tonal detail."]),
            ("Abstract styles", ["Abstract presets deliberately transform geometry. They are creative effects, not faithful photo conversions, and each exposes controls specific to its structure."]),
        ], ["preset-controls", "cartoon-preset", "color-photo-preset", "black-and-white-photo", "abstract-filters"]),
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
        [("Selected swatches", ["Enabled swatches define the available target colors. Pixels are assigned to suitable colors during processing, then same-color geometry is grouped for export."]), ("Layer settings", ["A layer needs matching Material Library data to be useful. If a chosen color has no matching setting, the pipeline may omit that color rather than fabricate unsafe laser parameters."]), ("Using an iridescent setting in the Rasterizer", ["The standard Rasterizer does not perform the Holographic Etching Lab's calibration, measured-color matching, or recipe-specific control of diffraction interval and angle. You can still map an ordinary palette swatch to a tested Material Library setting that produces an iridescent mark. Geometry assigned to that swatch will export on the matching layer and use that setting just like any other known material recipe.", "Choose or rename the swatch so its name matches the iridescent setting's Material Library Description, then inspect the exported layer in LightBurn. This is useful when one established iridescent treatment is enough; use the Holographic Etching Lab when you need a measured collection of angle- and interval-dependent recipes mapped across artwork."]), ("Color is not a guarantee", ["Palette color identifies a layer and intended recipe; it does not guarantee the physical color produced by a laser-marking process.", "For a clearer operator workflow, name each Material Library setting after the swatch closest to the color it is intended to produce. For example, a setting that produces a red mark should use one of the recognized names associated with a red-hue swatch. The default swatches are already named for this convention, making it easier to remember which recipe belongs to each layer when reviewing the project in LightBurn.", "The names may also be aligned in the opposite direction when an established Material Library already uses familiar terminology: rename the editable Rasterizer swatches to match those setting descriptions. Whichever direction you choose, keep the swatch name and Material Library Description consistent so the mapping is both machine-readable and easy for the operator to recognize."])],
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
        ["lightburn-large-projects", "pixel-size", "job-history", "image-presets"]),
    "lightburn-large-projects": _page(
        "When Large Vector Projects Make LightBurn Appear Unresponsive",
        "Why dense raster-to-vector projects can show Not Responding during framing, Start, or Send in LightBurn, how long to wait, and which cut optimizations to disable.",
        "A high-resolution or geometrically dense source image can become thousands of closed vector objects. LightBurn may need to perform enough geometry and job-planning work that its window temporarily displays “Not Responding.” That message can mean the interface is busy rather than that the calculation has failed.",
        [
            ("Why the project becomes demanding", ["Raster images store detail as a compact grid of pixels. After vectorization, that same detail may be represented by many separate paths, rectangles, vertices, holes, and color-layer boundaries. LightBurn must interpret those objects, apply layer behavior, prepare motion data, and sometimes compare large numbers of paths while planning the job.", "A file can therefore be valid and still require substantial CPU time and memory. High processing dimensions, many enabled colors, noisy source imagery, intricate silhouettes, dithered detail, and limited coalescing all contribute to the workload."]),
            ("First demanding point: Frame", ["Pressing Frame asks LightBurn to determine and execute a framing path for the selected project. With very dense vector artwork, preparing that action may require more calculation than the apparent simplicity of the outer boundary suggests.", "LightBurn may temporarily stop repainting its interface and Windows may label it Not Responding. Avoid repeatedly clicking Frame or other controls, because extra input does not make the active calculation finish sooner."]),
            ("Second demanding point: Start or Send", ["Pressing Start or Send causes LightBurn to prepare the actual machine job. It must process every enabled layer and its geometry, then generate or transmit the applicable job data. This is commonly the heaviest transition for a complex vectorized project.", "The delay occurs before the laser begins processing, but the operator should still remain with the machine and preserve normal fire-safety and supervision procedures. Never assume an unresponsive interface makes the machine safe to leave unattended."]),
            ("How long to wait", ["For a project that is known to contain dense generated geometry, allow LightBurn time to finish its calculation. Five to fifteen minutes can be reasonable for a large project, and an extreme project may take as long as roughly thirty minutes on some computers.", "These times are practical expectations, not a guarantee that every unresponsive session will recover. If the application remains unresponsive beyond the expected window, the computer begins exhausting memory, or the behavior repeats without completing, close or stop the workflow only when it is safe to do so and rebuild a less complex project."]),
            ("Cut optimization settings", ["For these color-separated generated projects, disable LightBurn cut optimizations other than ordering by layer. Leave Order by Layer enabled so the intended layer sequence remains the principal ordering rule.", "Path-level optimization options can cause LightBurn to compare and rearrange very large numbers of shapes. That search can take dramatically longer than processing the geometry in its existing layer organization, especially when thousands of closed regions are present. Review LightBurn’s optimization configuration before pressing Start or Send rather than changing it while a job is being prepared."]),
            ("Optional layer batching for extreme projects", ["For an exceptionally large project—or when a more responsive LightBurn session is more important than completing every layer in one submission—disable all but a small group of output layers and run only that group. After it completes, disable the finished layers, enable the next group, and run again. Continue until every intended layer has been processed.", "This reduces the amount of enabled geometry LightBurn must prepare for each Start or Send operation. It should normally be necessary only for large, high-resolution images with many vector objects or many complex color layers; ordinary projects are simpler and less error-prone when run as one reviewed job.", "Keep the workpiece, project origin, coordinate mode, device setup, focus, and fixture unchanged between batches so every group remains registered to the same artwork position. Maintain a written or visible record of completed layers, confirm that finished layers are disabled, and verify that only the next intended group is enabled before each run. Accidentally repeating a layer can change its appearance, add heat, or damage the result.", "Framing a reduced batch may describe only that batch’s enabled bounds rather than the complete artwork. Establish and verify the full-project placement before beginning, then avoid moving the material or changing the project geometry between batches. Continue normal supervision, extraction, and fire-safety practices for every individual run."]),
            ("When reducing complexity is the better answer", ["Waiting is useful when a one-time calculation is making steady progress, but it should not replace a practical project design. Reduce processing width or height, remove palette colors that do not contribute meaningful detail, simplify or clean noisy source artwork, and use the least aggressive detail settings that preserve the intended result.", "Keep a simpler version available for production if the full-detail project repeatedly strains LightBurn or the computer. The job logs and per-layer object counts can help identify which source color or processing stage contributes most of the geometry."]),
        ], ["reduce-lightburn-object-count", "raster-vs-vector", "lightburn-export", "works-with-lightburn", "job-history"]),
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
        [("Where to begin", ["If you already have a tested laser setting that produces an iridescent mark on your material, use that setting as the starting point for calibration. It gives the grid a known, productive foundation while the lab varies grating interval and direction to measure how the appearance changes. If you do not yet have such a setting, first develop a conservative material test that produces a clean, repeatable mark."]), ("The workflow", ["Generate and engrave a calibration grid; photograph it under a controlled viewing and lighting setup; analyze and review measured cells; save useful recipes; then build Holographic Artwork."]), ("Why calibration is necessary", ["Diffraction appearance depends on grating geometry, scan direction, laser parameters, surface, lighting, and viewing angle. A recipe measured in one setup may not reproduce identically in another."]), ("Experimental status", ["This feature prepares geometry and settings for testing. It does not promise a particular physical color or certify a laser process."])],
        ["what-is-iridescence", "iridescent-laser-engraving", "iridescent-engraving-challenges", "holographic-lab-workflow"]),
    "what-is-iridescence": _page(
        "What Is Iridescence?",
        "Learn why iridescent surfaces appear to change color with lighting and viewing angle and how structural color differs from pigment.",
        "Iridescence is an angle-dependent visual effect: the apparent color or brightness of a surface changes as the light, surface, or viewer moves. A soap bubble, an oil film, a compact disc, and some insect wings are familiar examples.",
        [("Color made by structure", ["Pigments absorb some wavelengths and reflect others. Structural color instead comes from microscopic features that interfere with, scatter, or diffract light. The observed result depends on feature spacing, orientation, and the geometry between the light source, surface, and viewer."]), ("Why the color moves", ["Think of the surface as a field of extremely fine optical traffic directors. Changing the viewing angle changes which wavelengths are directed toward the eye, so a mark may shift hue, become brighter, or disappear even though the material itself has not changed."]), ("Iridescent is not a fixed color", ["A camera RGB value records one observation under one optical arrangement. It is useful as a calibrated lookup for that arrangement, but it is not a universal paint-chip specification. Always evaluate the result under the lighting and viewing conditions relevant to the finished work."])],
        ["diffraction-gratings", "iridescent-laser-engraving", "holographic-etching"]),
    "iridescent-laser-engraving": _page(
        "Iridescent Laser Engraving and Structural Color",
        "How fine laser-marked structures can create iridescent, angle-dependent appearances on suitable materials.",
        "Iridescent laser engraving uses controlled, closely spaced marks to alter how a surface reflects and diffracts light. On a suitable material, these structures can produce changing highlights or color without applying colored ink.",
        [("How the laser contributes", ["Scan interval and direction organize the surface pattern, while power, speed, frequency, pulse width, focus, passes, and material response determine the physical marks that actually remain. The requested hatch pattern is therefore only one part of the optical result."]), ("Start from a known mark", ["If a tested setting already produces a clean iridescent mark on the chosen material, use it as the base setting for a Holographic Etching Lab calibration. The grid can then explore interval and angle around a foundation you already know the laser and surface can reproduce."]), ("A simpler Rasterizer option", ["When you already have one trusted iridescent Material Library setting and do not need calibrated diffraction recipes, a normal Rasterizer swatch can be named to match that setting. Pixels mapped to the swatch will use the iridescent setting on their exported LightBurn layer. This does not add the lab's measured angle and interval behavior, but it provides a straightforward way to include a known iridescent treatment in ordinary color-separated artwork."]), ("Inspect from several directions", ["A useful result should be evaluated while moving the light and viewing position. A mark that looks vivid from one direction may look neutral from another, which can be intentional but must be understood before designing artwork around it."]), ("Not every surface responds equally", ["Material composition, finish, coating, preparation, flatness, focus, and lens can all change the microscopic structure and its appearance. Test coupons are essential before engraving valuable work."])],
        ["what-is-iridescence", "iridescent-engraving-challenges", "holographic-calibration", "mopa-laser-workflow"]),
    "iridescent-engraving-challenges": _page(
        "Challenges of Iridescent Laser Engraving",
        "Understand the repeatability, measurement, material, viewing-angle, and calibration challenges of laser-generated iridescence.",
        "Producing an iridescent mark once is different from producing a controlled palette repeatedly. Small changes in the machine, surface, or observation setup can shift the result.",
        [("Many variables interact", ["Interval and scan angle interact with speed, power, frequency, pulse width, passes, focus, lens, and the material response. Changing one control may alter groove shape, heat accumulation, oxidation, or reflectivity rather than changing only hue."]), ("Appearance depends on observation", ["Lighting direction, light-source spectrum, camera exposure, white balance, and viewing angle all affect the recorded color. Comparing tests captured under different conditions is like comparing paint samples under different lamps."]), ("Repeatability is physical", ["Surface finish, contamination, coating thickness, workpiece flatness, focus drift, and machine condition can prevent a saved recipe from reproducing exactly. Recipes should be treated as measured starting points for a controlled setup, not guarantees."]), ("Dense artwork has production costs", ["Small holographic pixels and many measured colors can create numerous closed shapes and LightBurn layers. This may increase export size and the time LightBurn needs to frame, optimize, send, or start a job."])],
        ["holographic-lab-workflow", "analyze-calibration-photo", "reduce-lightburn-object-count", "lightburn-large-projects"]),
    "holographic-lab-workflow": _page(
        "How the Holographic Etching Lab Helps",
        "How calibration grids, photo analysis, saved recipes, and LightBurn exports make experimental iridescent engraving more systematic.",
        "The Holographic Etching Lab does not remove the physical uncertainty of structural color. It turns trial and error into a recorded calibration workflow so useful observations can be reviewed, saved, and applied consistently to artwork.",
        [("It creates known experiments", ["The calibration profile records grid dimensions and the requested interval, scan angle, and optional setting sweep for each cell. Labels, fiducials, and the calibration identifier keep the physical test associated with the correct data."]), ("It connects observations to settings", ["Photo analysis samples the engraved grid using its saved layout. You can review measured colors and quality indicators, then retain trusted cells as a Holographic Recipe instead of relying on memory or handwritten coordinates alone."]), ("It maps artwork systematically", ["Artwork colors are matched to measured recipe colors. The exporter groups adjacent pixels and assigns geometry to recipe-specific LightBurn layers, carrying the measured interval and angle into a project that can be inspected before production."]), ("It preserves operator judgment", ["You still choose the base Material Library setting, control the photograph and viewing setup, reject unreliable samples, inspect the LightBurn project, and test the final material. The lab organizes evidence; it does not certify a color or a safe machine process."])],
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

DOCS["raster-to-vector"]["diagram"] = {
    "src": "/static/docs/raster-pipeline.svg",
    "alt": "Artwork passes through resizing and palette mapping, vector-region construction, Material Library layer assignment, and SVG and LightBurn export.",
    "caption": "The Rasterizer prepares geometry and layer settings, then hands the project to LightBurn.",
}
DOCS["raster-vs-vector"]["diagram"] = {
    "src": "/static/docs/raster-vs-vector.svg",
    "alt": "A raster circle made from colored grid cells is compared with a vector circle described by a mathematical path and anchor points.",
    "caption": "Raster graphics store colored cells; vector graphics store geometric instructions. The Rasterizer translates selected pixel regions into editable vector shapes.",
}
DOCS["color-layers"]["diagram"] = {
    "src": "/static/docs/color-setting-map.svg",
    "alt": "Editable Rasterizer swatch names map to matching Material Library descriptions and recognizable LightBurn color layers.",
    "caption": "Consistent swatch and setting names make mappings easier for the application and operator to recognize.",
}
DOCS["holographic-etching"]["diagram"] = {
    "src": "/static/docs/holographic-calibration-loop.svg",
    "alt": "The holographic workflow generates and engraves a test grid, photographs and analyzes it, saves trusted recipes, and maps artwork to those recipes.",
    "caption": "Holographic Artwork is built from a measurement loop rather than an assumed universal color table.",
}
DOCS["works-with-lightburn"]["diagram"] = {
    "src": "/static/docs/lightburn-companion.svg",
    "alt": "MOPA Laser Rasterizer prepares image geometry, layers, and settings before LightBurn is used for inspection, layout, device configuration, framing, and laser operation.",
    "caption": "The application is a preparation assistant for LightBurn, not a replacement or laser controller.",
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
CONTROL_GUIDES = {
    "min_island_area": ("Minimum island area", "Removes isolated regions smaller than the selected processed-area threshold.", "Like using a sieve that lets tiny crumbs fall through while keeping larger pieces."),
    "simplification_factor": ("Simplification", "Reduces small boundary bends and vector points while retaining the larger silhouette.", "Like tracing a coastline with a broader pencil that skips the smallest coves."),
    "smoothing_radius": ("Smoothing radius", "Rounds small corners and calms jagged region boundaries.", "Like sanding a cut edge with progressively more rounding pressure."),
    "transparent": ("Transparent light areas", "Leaves the light half of the black-and-white result unengraved instead of exporting light geometry.", "Like printing black ink on clear film and treating the unprinted film as empty space."),
    "amplitude_x": ("Horizontal amplitude", "Sets side-to-side displacement.", "The reach of a flag waving left and right."),
    "amplitude_y": ("Vertical amplitude", "Sets up-and-down displacement.", "The height of waves on water."),
    "frequency_x": ("Horizontal frequency", "Sets how quickly the vertical wave repeats across the artwork.", "Fitting more waves along the same rope."),
    "frequency_y": ("Vertical frequency", "Sets how quickly the horizontal wave repeats down the artwork.", "Moving contour lines closer together."),
    "phase": ("Phase", "Slides a repeating effect through its cycle.", "Sliding striped wallpaper without changing stripe width."),
    "cell_size": ("Cell size", "Sets the scale of cells or facets.", "Choosing paving stones instead of mosaic pieces."),
    "jitter": ("Jitter", "Moves regular cell seeds by a controlled random amount.", "Nudging trees away from their points on a planting grid."),
    "gap": ("Gap", "Opens space between cells, tiles, or facets.", "Widening grout between floor tiles."),
    "seed": ("Seed", "Selects a repeatable random arrangement.", "Recording a shuffle number so the same deck order can be recreated."),
    "shear_x": ("Horizontal shear", "Slants horizontal position with height.", "Pushing the top of a stack of cards sideways."),
    "shear_y": ("Vertical shear", "Slants vertical position with width.", "Pushing one side of a soft frame upward."),
    "scale_x": ("Horizontal scale", "Stretches or compresses width.", "Changing only a photograph's width."),
    "scale_y": ("Vertical scale", "Stretches or compresses height.", "Changing only a photograph's height."),
    "twist": ("Twist", "Sets rotation amount and direction around the center.", "Stirring paint clockwise or counterclockwise."),
    "falloff": ("Falloff", "Distributes twist strength by distance from the center.", "Choosing whether a whirlpool turns near the drain or across the basin."),
    "center_x": ("Center X", "Moves the effect origin left or right.", "Moving a compass point horizontally."),
    "center_y": ("Center Y", "Moves the effect origin up or down.", "Moving a compass point vertically."),
    "tile_size": ("Tile size", "Sets mosaic block size.", "Choosing bathroom mosaic tiles or large floor tiles."),
    "stagger": ("Stagger", "Offsets alternating rows by part of a tile.", "Changing graph paper into a brick-wall bond."),
    "amplitude": ("Amplitude", "Sets ripple displacement strength and direction.", "Changing how strongly a stone disturbs water."),
    "frequency": ("Frequency", "Sets how closely ripple cycles repeat.", "Changing a topographic map's contour interval."),
    "dark_threshold": ("Dark threshold", "Chooses how dark a pixel must be to count as ink.", "Adjusting a photocopier until faint pencil marks appear or disappear."),
    "contrast": ("Contrast", "Separates dark ink from nearby tones.", "Increasing scanner contrast to distinguish a signature from paper texture."),
    "blur": ("Blur", "Suppresses small noise before tracing.", "Viewing grain through lightly frosted glass so specks blend together."),
    "gap_closure": ("Gap closure", "Reconnects nearby breaks in dark strokes.", "Bridging hairline cracks before tracing a road."),
    "line_simplification": ("Line simplification", "Reduces small bends and path points.", "Redrawing a shaky line with fewer smooth turns."),
    "min_branch_length": ("Minimum branch length", "Removes short centerline offshoots.", "Pruning twigs while keeping a tree's main limbs."),
    "stroke_width": ("Stroke width", "Sets the closed ribbon width around each centerline.", "Changing from a technical pen to a broad marker."),
    "slice_height": ("Slice height", "Sets horizontal glitch-band thickness.", "Cutting a poster into thin or thick ribbons."),
    "fragment_width": ("Fragment width", "Sets typical glitch-chunk length.", "Cutting those ribbons into short or long pieces."),
    "shift_amount": ("Shift amount", "Sets sideways fragment travel.", "Misaligning one row in a screen-print pass."),
    "echo_count": ("Echo count", "Sets the number of repeated displaced copies.", "Adding repeats with an audio delay effect."),
    "echo_spacing": ("Echo spacing", "Sets distance between repeated copies.", "Changing gaps in a photographic motion trail."),
    "density": ("Density", "Sets how much eligible geometry participates.", "Choosing what percentage of a building's windows are lit."),
    "fibonacci_stride": ("Fibonacci stride", "Changes the step through a Fibonacci displacement rhythm.", "Taking every second or fifth beat from a drum pattern."),
    "vertical_jitter": ("Vertical jitter", "Adds repeatable vertical wobble.", "A television picture with unstable horizontal hold."),
    "block_size": ("Block size", "Sets compression-like chunk scale.", "Choosing pixel size in a deliberately low-resolution image."),
    "band_height": ("Band height", "Sets damaged scan-band height.", "Dividing a page with a marker instead of a fine pen."),
    "compression_gap": ("Compression gap", "Opens seams between blocks.", "Exposing missing mortar between damaged bricks."),
    "smear_amount": ("Smear amount", "Drags selected bands sideways.", "Wiping wet ink with a cloth."),
    "degradation": ("Degradation", "Raises the share of damaged or omitted chunks.", "Repeatedly photocopying an image until pieces fail."),
    "min_shard_size": ("Minimum shard size", "Sets the smallest generated fragment.", "Rejecting splinters smaller than a sieve opening."),
    "max_shard_size": ("Maximum shard size", "Sets the largest generated fragment.", "Limiting pieces with a sorting screen."),
    "minimum_gap": ("Minimum gap", "Sets the narrowest crack between shards.", "Choosing the thinnest grout line in a broken-tile mosaic."),
    "gap_variation": ("Gap variation", "Makes crack widths less uniform.", "Natural glass cracks opening by different amounts."),
    "horizontal_spread": ("Horizontal spread", "Moves shards sideways.", "Debris spreading outward after impact."),
    "fall_distance": ("Fall distance", "Moves shards downward.", "Broken pieces dropping under gravity."),
    "gravity_bias": ("Gravity bias", "Controls how strongly movement favors downward fall.", "Turning up gravity in a physics simulation."),
    "rotation": ("Rotation", "Sets shard tumbling.", "Loose cards spinning as they fall."),
    "break_origin_x": ("Break origin X", "Moves the impact point left or right.", "Moving a hammer strike across glass."),
    "break_origin_y": ("Break origin Y", "Moves the impact point up or down.", "Moving that strike higher or lower."),
}

filter_manifest = abstract_filter_manifest()
for slug, (name, behavior) in FILTER_PAGES.items():
    DOCS[f"{slug}-filter"] = _page(
        f"{name} Abstract Vector Filter",
        f"Use the {name} preset to transform raster-derived color regions into laser-ready abstract vector geometry.",
        f"{name} is an optional creative preset that {behavior}. It operates within the normal palette, Material Library, job logging, and LightBurn export workflow.",
        [("Best use", ["Start with a recognizable subject or strong color silhouette. The effect is intentionally interpretive, so test a small processing size before committing to a detailed export."]), ("Controls", ["The preset panel exposes only the parameters supported by this filter. Larger or denser values can increase processing time and object count depending on the source geometry."]), ("Output", ["The transformed regions remain assigned to their applicable color layers and Material Library settings. Inspect the final SVG and LBRN2 project before engraving."])],
        ["abstract-filters", "abstract-filter-reference", "reduce-lightburn-object-count"],
    )
    module_slug = slug.replace("-", "_")
    filter_data = filter_manifest.get(module_slug, {})
    defaults = filter_data.get("defaults", {})
    DOCS[f"{slug}-filter"]["controls"] = [
        {
            "name": control["name"], "label": CONTROL_GUIDES[control["name"]][0],
            "effect": CONTROL_GUIDES[control["name"]][1], "analogy": CONTROL_GUIDES[control["name"]][2],
            "default": defaults.get(control["name"]), "minimum": control["min"],
            "maximum": control["max"], "step": control["step"],
        }
        for control in filter_data.get("controls", [])
    ]

STANDARD_PRESET_CONTROLS = {
    "cartoon-preset": [
        ("min_island_area", 0, 0, 100, 1), ("simplification_factor", 0, 0, 5, .05),
        ("smoothing_radius", .001, 0, 10, .001),
    ],
    "color-photo-preset": [
        ("min_island_area", 8, 0, 100, 1), ("simplification_factor", .35, 0, 5, .05),
        ("smoothing_radius", .5, 0, 10, .05),
    ],
    "black-and-white-photo": [
        ("min_island_area", 2, 0, 100, 1), ("simplification_factor", .1, 0, 5, .05),
        ("smoothing_radius", .1, 0, 10, .05), ("transparent", False, False, True, 1),
    ],
}
for page_slug, controls in STANDARD_PRESET_CONTROLS.items():
    DOCS[page_slug]["controls"] = [
        {
            "name": name, "label": CONTROL_GUIDES[name][0], "effect": CONTROL_GUIDES[name][1],
            "analogy": CONTROL_GUIDES[name][2], "default": default,
            "minimum": minimum, "maximum": maximum, "step": step,
            "kind": "toggle" if isinstance(default, bool) else "number",
        }
        for name, default, minimum, maximum, step in controls
    ]


DOC_GROUPS = [
    ("Rasterizer", ["preset-controls", "raster-to-vector", "raster-vs-vector", "image-presets", "cartoon-preset", "color-photo-preset", "black-and-white-photo", "pixel-size", "color-layers"]),
    ("Abstract filters", ["abstract-filters", "abstract-filter-reference"] + [f"{slug}-filter" for slug in FILTER_PAGES]),
    ("LightBurn and materials", ["works-with-lightburn", "material-vault", "material-libraries", "lightburn-export", "lightburn-large-projects", "reduce-lightburn-object-count", "mopa-laser-workflow"]),
    ("Holographic Etching Lab", ["holographic-etching", "what-is-iridescence", "iridescent-laser-engraving", "iridescent-engraving-challenges", "holographic-lab-workflow", "holographic-calibration", "analyze-calibration-photo", "holographic-recipes", "holographic-artwork", "diffraction-gratings", "choose-cut-mode"]),
    ("Jobs and support", ["job-history", "troubleshooting"]),
]
DOC_ORDER = [slug for _group, slugs in DOC_GROUPS for slug in slugs]


@routes.route("/docs")
def docs_index():
    return render_template("docs.html", page=None, pages=DOCS, groups=DOC_GROUPS,
                           canonical=_canonical("/docs"), previous_page=None, next_page=None)


@routes.route("/docs/<slug>")
def docs_page(slug):
    page = DOCS.get(slug)
    if not page:
        return render_template("docs.html", page=None, pages=DOCS, groups=DOC_GROUPS,
                               canonical=_canonical("/docs"), previous_page=None, next_page=None), 404
    page_index = DOC_ORDER.index(slug)
    previous_slug = DOC_ORDER[page_index - 1] if page_index else None
    next_slug = DOC_ORDER[page_index + 1] if page_index + 1 < len(DOC_ORDER) else None
    return render_template("docs.html", page=page, slug=slug, pages=DOCS, groups=DOC_GROUPS,
                           canonical=_canonical(f"/docs/{slug}"),
                           previous_page=(previous_slug, DOCS[previous_slug]) if previous_slug else None,
                           next_page=(next_slug, DOCS[next_slug]) if next_slug else None)


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

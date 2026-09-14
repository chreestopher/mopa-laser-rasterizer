# Spatially grouped punch-through experiment

This directory is an isolated duplicate of the production command-line
rasterizer under `lib/`. Production website and CLI files are unchanged.

This copy retains the production synthetic Black canvas and punch-through
geometry. Its experimental difference is output grouping:

- Each outer colored region becomes a movable group.
- Colored shapes located inside that exterior ring join the same group.
- Colored exterior-region groups contain only objects assigned to their color
  layer.
- The synthetic canvas and every Black punch-through copy are grouped together
  in a Black-only LightBurn group.
- Rendered Black SVG geometry is likewise placed only in the Black SVG group.
- SVG output uses equivalent `<g>` region groups.
- The complete Black canvas is emitted only once.

The Black canvas and all of its nested punch paths now share the same parent
group, preserving their fill relationship when LightBurn fills by group.

The experimental CLI also accepts the opt-in filter parameter
`"constrain_nonblack": true`. When enabled for ordinary color quantization, it
builds a mask from pixels that are exactly RGB `#000000` in the original source,
resizes that binary mask with nearest-neighbor sampling, removes Black from the
palette used for every other pixel, then restores only those masked pixels to
Black. Detecting Black before the normal Lanczos image resize prevents
interpolation from manufacturing new Black pixels. Dark non-Black source
pixels must therefore select the nearest configured non-Black swatch.

This option constrains source-pixel quantization only. It does not prohibit a
preset or abstract filter from deliberately generating Black geometry later in
processing. The specialized two-color Black-and-White Photo preset retains its
existing behavior. `experiments/run-sample.sh` enables the option; other
experimental CLI calls leave it disabled unless explicitly requested.

Krasnow also replaces the general Abstract preset's aggressive geometry
cleanup defaults. Its default smoothing radius is 0.001 and simplification is
disabled so nearby Black source outlines are not closed together into solid
blobs. Source Black then enters the same patch-and-grating remap as every other
input color. It is not restored as a solid Black fill; its grating paths are
distributed across the calibrated non-Black carrier layers. Explicit CLI
filter parameters still override the cleanup defaults.

Run it through the repository WSL virtual environment:

```bash
bash experiments/run-cli.sh INPUT OUTPUT_BASE PIXEL_MM WIDTH HEIGHT MATERIAL_LIBRARY MATERIAL COLORS PRESET FILTER [FILTER_JSON] [PALETTE_NAMES_JSON] [SVG_ONLY]
```

The argument format matches `lib/Material_Library.py`.

Run only the focused experiment tests with:

```bash
bash experiments/run-tests.sh
```

If `test-input.png` and `tests.clb` are in the repository root, the prior
hardcoded sample configuration is available through:

```bash
bash experiments/run-sample.sh
```

This uses all 30 default swatches, `colors - stainless steel`, 0.125 mm pixel
size, 800-pixel width, Cartoon processing, and minimum island area 50. It has
not been run automatically.

# Color Discovery: LightBurn Material Test Presets

Color Discovery offers two output formats:

- **LightBurn Project (.lbrn2)**: the established automatically packed square-cell
  grid, with a separate layer per cell and the existing layer limit.
- **LightBurn Material Test Preset (.lbmt)**: an experimental native Material Test
  preset. Rows and columns are independent and default to 10 each. Cell width and
  height are derived from the existing Color Discovery grid width and length.

Both use the selected library setting and the Labels choice (automatically
selected when available, with a user override). The preset also uses that selected
label setting for its optional border, but exports that border with output disabled
by default. No machine configuration is exported or replaced.

## Choose the appropriate format

Use `.lbrn2` when you want an ordinary editable LightBurn project and its supported
parameter axes fit within the available layer count. Use `.lbmt` when you want a
larger native Material Test matrix, independent row and column counts, and one of
the currently supported native sweep pairs. A 10 × 10 `.lbmt` preset contains 100
test cells without requiring 100 LightBurn color layers.

The two files are not interchangeable. An `.lbrn2` file opens as a project. An
`.lbmt` file is imported into LightBurn's Material Test tool and then reviewed in
that tool's Preview before use.

## Generate and use a preset

1. In Color Discovery choose `.lbmt`, the overall grid dimensions, rows and columns, cut mode,
   starting setting, Labels setting and two sweep axes.
2. Download the preset and keep its metadata. The service also saves metadata for
   later grid lookup, subject to the existing retention period.
3. In LightBurn open **Laser Tools → Material Test → Import** and select the preset
   named `Rasterizer <short Grid ID>`.
4. Review the material, text, and border settings, their enabled states, positioning, and
   the complete Preview. Matrix dimensions do not include labels or any native
   spacing. Confirm the complete test fits the material and your configured field.
5. Run the test using your existing LightBurn device and appropriate precautions.
6. Select that Grid ID in Color Discovery and load the photograph. Align the four
   corners to the cell matrix, excluding labels. Keep the photo oriented with
   frequency/other column values increasing to the right and row values increasing
   upward, as shown in LightBurn Preview.

The Grid ID is in the preset name, **not engraved**. Keep the downloaded metadata
with the preset. Do not modify the axes, counts,
or laser settings after export if you intend to use the saved calibration metadata.
Regenerate from Rasterizer instead. Label font size is left to LightBurn.

## Understand sizing and positioning

Rasterizer derives cell width and height from the requested overall grid width and
length, selected row and column counts, LightBurn's 1 mm inter-cell gaps, and the
space reserved for native title and axis text. Cell dimensions are therefore
outputs, not separate fields to enter.

The preset's X Center and Y Center default to half of the requested grid width and
length. This centers the described overall test area around those coordinates; it
does not prove that the complete native labels fit a particular machine field.
Always use LightBurn Preview to inspect the entire result against the active device
and material before running it.

## Current support and limits

- Supported sweep axes: Speed, Maximum power, Fill interval, Frequency.
- Other axes remain available for `.lbrn2`; their preset identifiers have not yet
  been verified with exported samples.
- Frequency inputs and metadata use Hz. Native preset frequency bounds use kHz;
  embedded cut frequency values still use Hz.
- Native sweeps use linear interpolation, unlike the legacy project's flooring
  of integer parameters. Metadata stores nominal interpolated values; actual
  LightBurn/controller rounding still needs physical verification. Displayed label
  rounding alone does not establish the exact emitted value.
- The preset cut-mode selector supports Fill, Line, and Offset Fill. The selected
  setting supplies its top-level laser values. An explicit cut mode deliberately
  omits additional LightBurn sublayers because a native Material Test preset has
  one material operation.
- Rasterizer currently permits 2–100 rows/columns and at most 400 total cells.
  Rasterizer reserves 10% of the requested width, and 10% plus another 10 mm of
  the requested height, for LightBurn's title and axis labels. LightBurn also
  places a fixed 1 mm gap between neighboring
  Material Test cells, so Rasterizer subtracts those gaps before dividing the
  remaining matrix area into cells. X Center and Y Center default to half of the requested
  grid width and length. The optional border uses the selected Labels setting but
  is exported with output disabled by default. A metadata-size safeguard may require fewer cells for
  complex settings. These are application safeguards, not claimed LightBurn limits.
- Refinement preserves the source format and dimensions.

## Verify before engraving

Confirm the device, material, focus, fixture, complete matrix dimensions, label
clearance, cut mode, fixed settings, sweep endpoints, row and column directions,
and every emitted value in LightBurn. Start on a small expendable coupon and remain
within the laser source, controller, lens, and material limits. Generated files and
metadata do not validate the physical safety or repeatability of a setting.

Rasterizer tests cover serialization, frequency unit conversion, rectangular
dimensions, label selection, top-to-bottom photo indexing, default 100-cell grids,
rejected inputs, and preservation of `.lbrn2` behavior. They do not replace physical
validation of native sweep rounding or an end-to-end photographed calibration on
your machine.

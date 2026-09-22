# Color Discovery: LightBurn material-test presets

The serverless Color Discovery page offers two output formats:

- **LightBurn Project (.lbrn2)**: the existing automatically packed square-cell grid,
  with a separate layer per cell and the existing layer limit.
- **LightBurn Material Test Preset (.lbmt)**: an experimental native Material Test
  preset. Rows and columns are independent, defaulting to 10 each. Cell width and
  height are derived from the existing Color Discovery grid width and length.

Both use the selected library setting and the existing Labels choice (automatically
selected when available, with a user override). The preset also uses that selected
label setting for its border. No machine configuration is exported or replaced.

## Using a preset

1. Choose `.lbmt`, the overall grid dimensions, rows and columns, cut mode,
   starting setting, Labels setting and two sweep axes.
2. Download the preset and keep its metadata. The service also saves metadata for
   later grid lookup, subject to the existing retention period.
3. In LightBurn open **Laser Tools → Material Test → Import** and select the preset
   named `Rasterizer <short Grid ID>`.
4. Review material, text and border settings, their enabled states, positioning and
   the complete Preview. Matrix dimensions do not include labels or any native
   spacing. Confirm the complete test fits the material and your configured field.
5. Run the test using your existing LightBurn device and appropriate precautions.
6. Select that Grid ID in Color Discovery and load the photograph. Align the four
   corners to the cell matrix, excluding labels. Keep the photo oriented with
   frequency/other column values increasing to the right and row values increasing
   upward, as shown in LightBurn Preview.

The Grid ID is in the preset name, **not engraved**. Do not modify the axes, counts,
or laser settings after export if you intend to use the saved calibration metadata.
Regenerate from Rasterizer instead. Label font size is left to LightBurn.

## Initial support and limits

- Supported sweep axes: Speed, Maximum power, Fill interval, Frequency.
- Other axes remain available for `.lbrn2`; their preset identifiers have not yet
  been verified with exported samples.
- Frequency inputs and metadata use Hz. Native preset frequency bounds use kHz;
  embedded cut frequency values still use Hz.
- Native sweeps use linear interpolation, unlike the legacy project's flooring
  of integer parameters. Metadata stores nominal interpolated values; actual
  LightBurn/controller rounding still needs physical verification. Displayed label
  rounding alone does not establish the exact emitted value.
- The preset cut-mode selector supports Fill, Line and Offset Fill. The selected
  setting supplies its top-level laser values. An explicit cut mode deliberately
  omits additional LightBurn sublayers because a native Material Test preset has
  one material operation.
- Rasterizer currently permits 2–100 rows/columns and at most 400 total cells.
  LightBurn places a fixed 1 mm gap between neighboring Material Test cells, so
  Rasterizer subtracts those gaps before dividing the requested grid width and
  length into cells. X Center and Y Center default to half of the requested grid
  width and length. A metadata-size safeguard may require fewer cells for complex
  settings. These are application safeguards, not claimed LightBurn limits.
- Refinement preserves the source format and dimensions.

## Verification

Local tests cover serialization, frequency unit conversion, rectangular dimensions,
label selection, top-to-bottom photo indexing, default 100-cell grids, rejected
inputs and preservation of `.lbrn2` behavior. This is not yet a physical validation
of native sweep rounding or an end-to-end photographed calibration.

# Reproducing Krasnow Grating Geometry by Hand

This guide explains what MOPA Laser Rasterizer does **after ordinary vector regions have been created from the source image**, and translates that process into a workflow that can be reproduced without Rasterizer.

The result is best described as angular diffraction artwork, or a fauxlogram. It is not a true wavefront-recorded hologram. The apparent color and motion come from many small fields of parallel vector lines combined with calibrated, microscopic pulse spacing on the engraved surface.

The method has two independent scales:

1. **Visible vector geometry** divides the artwork into small cells and fills each cell with parallel open paths. The original image controls the orientation and placement of these paths.
2. **Microscopic carrier settings** assign those paths to several LightBurn layers. The layers share one calibrated laser recipe but use different speeds, producing different along-path pulse pitches at a fixed frequency.

Keeping those two scales separate is essential. The visible distance between neighboring vector paths is not the same thing as the microscopic distance between laser pulses along each path.

## What you need before beginning

Start with:

- the original raster image, retained at the same crop and aspect ratio as the vectors;
- closed, color-separated vector regions made from that image;
- a known physical artwork size;
- a tested Cut/Line-mode laser setting that produces a strong iridescent result on the intended machine, lens, focus, material, surface finish, and preparation;
- several available LightBurn layers to serve as diffraction carriers; and
- a small physical calibration test before attempting final artwork.

The vector regions should not overlap. If two source colors cover the same point, choose one deterministic owner before building gratings. Rasterizer resolves conflicts in native LightBurn layer order, allowing the first layer to own the point and subtracting that occupied area from later layers.

Black may be handled in either of two ways:

- **Preserved Black:** retain source-black regions as ordinary closed geometry using the normal Black laser setting. Black is not a diffraction carrier.
- **Grated Black:** treat Black like every other source region and allow the Fauxlographic carrier setting to be cloned onto the Black layer.

Rasterizer normally preserves source Black.

## The three decisions made for every cell

After vectorization, every grating cell must answer three separate questions:

| Decision | Controlled by | Changes |
|---|---|---|
| Where does geometry exist? | The intersection of the source vector region and the cell shape | The visible silhouette and clipping boundary |
| Which direction do the paths run? | Original source-image luminance, or an explicit painted flow guide | The local grating orientation |
| Which carrier layer receives the paths? | Artwork position, gradient settings, and the assigned swatch hue | The laser speed and microscopic pulse pitch |

These decisions are independent. A gradient start or end value does **not** rotate the paths, change the cell size, change the number of paths, or directly change their visible spacing. It selects among carrier layers.

## 1. Establish one coordinate system

Place the original image and all vector regions in the same coordinate system. Record the complete artwork bounds:

```text
(artwork_left, artwork_top, artwork_right, artwork_bottom)
```

The cell grid must be anchored to these bounds, not independently to each colored region. A shared origin keeps adjacent colors aligned and prevents cell patterns from jumping at color boundaries.

When reproducing the process in a vector editor, lock the source image in place beneath the vectors. It will still be needed for brightness sampling even though the final output is vector geometry.

## 2. Make the cell grid

Choose a physical patch size. Rasterizer's default square patch is **0.4 mm** wide and high.

For square cells, begin at the artwork's top-left corner and create a regular grid:

```text
cell_left = artwork_left + column_index * patch_size
cell_top  = artwork_top  + row_index    * patch_size
```

Retain partial boundary cells. Do not shift or resize the grid to fit an individual vector region.

Rasterizer also supports hexagons, equilateral triangles, diamonds/rhombi, puzzle pieces, and decorative silhouettes. Square, hexagon, triangle, diamond, and puzzle-piece layouts are intended to cover the plane without deliberate gaps. Decorative shapes such as skulls, hearts, bats, ghosts, alien heads, paw prints, fish scales, and space invaders intentionally leave exposed substrate between cells.

For a manual first attempt, use squares. They make alignment, clipping, and troubleshooting much easier.

## 3. Intersect each cell with the source vectors

For every source-color region and every grid cell that touches it:

1. duplicate the cell shape;
2. intersect it with the closed source-color region;
3. discard an empty intersection; and
4. retain the intersection as the clipping area for that cell.

The clipping area may be a full cell, a partial cell at an edge, several disconnected pieces, or a shape containing holes. All later line construction is clipped to this exact result.

The source vector color remains useful metadata. Rasterizer uses the hue of the region's assigned palette swatch when selecting a carrier and when optionally changing visible line spacing. It does not sample a different original-image hue for every cell.

## 4. Determine the grating angle from source brightness

Sample the original raster image at the center of the cell, convert that sample to 8-bit grayscale, and call the result `L`, from 0 for black to 255 for white.

Map it linearly between the chosen minimum and maximum angles:

```text
angle_control = angle_min + (L / 255) * (angle_max - angle_min)
```

With Rasterizer's defaults:

```text
angle_min = -90 degrees
angle_max = +90 degrees
```

Therefore:

- black samples map to -90 degrees;
- middle gray maps to approximately 0 degrees; and
- white samples map to +90 degrees.

There is one implementation detail to preserve when matching Rasterizer exactly: `angle_control` describes the **normal across the family of lines**. The actual path direction is perpendicular to it:

```text
path_direction = angle_control + 90 degrees
```

So an `angle_control` of 0 degrees produces vertical paths, while an `angle_control` of 90 degrees produces horizontal paths. If another vector tool defines hatch angle as the direction of the path itself, add 90 degrees before entering the value.

This brightness-to-angle stage is what retains recognizable shading and form after the filled source vectors are replaced by line gratings.

## 5. Choose the visible spacing between paths

Rasterizer's default visible line spacing is **0.06 mm**. This is the perpendicular distance from one generated vector path to the next within a cell.

For neutral or weakly saturated source swatches, use the ordinary line spacing.

For saturated source swatches, Rasterizer can optionally vary the visible spacing between a user-selected violet minimum and red maximum. It approximates the following hue-to-wavelength order:

| Swatch hue | Approximate wavelength proxy |
|---|---:|
| Violet | 400 nm |
| Blue | 460 nm |
| Cyan | 490 nm |
| Green | 530 nm |
| Yellow | 580 nm |
| Orange | 600 nm |
| Red | 650 nm |

Intermediate hues are interpolated. Purple and magenta are not single spectral wavelengths, so Rasterizer uses a continuous proxy that returns from violet toward red. If the minimum and maximum spacing are equal, every chromatic region uses the same visible spacing.

Again, this is **macroscopic path spacing**. It affects geometry density and file size, but it is separate from the microscopic pulse pitch that creates the diffraction response.

## 6. Draw the parallel open paths

Let the cell center be `(cx, cy)` and let `theta` be `angle_control` in radians.

Construct a unit normal and a perpendicular unit tangent:

```text
normal  = (cos(theta),  sin(theta))
tangent = (-sin(theta), cos(theta))
```

The normal points across the family of paths. The tangent points along each path.

Next:

1. Find half the diagonal length of the cell's bounding box.
2. Sweep an offset from negative half-diagonal to positive half-diagonal in increments of the visible line spacing.
3. At each offset, move from the cell center along the normal:

   ```text
   anchor = cell_center + normal * offset
   ```

4. Through that anchor, draw a line long enough to cross the complete cell in both tangent directions.
5. Intersect that candidate line with the clipped source-region/cell intersection.
6. Keep every nonzero-length line fragment as an open path.

In pseudocode:

```text
for offset from -half_diagonal to +half_diagonal step visible_spacing:
    anchor = center + normal * offset
    candidate = long_line(anchor - tangent * reach,
                          anchor + tangent * reach)
    output_fragments += intersect(candidate, source_region AND cell)
```

This double clipping is important. The paths must stay inside both the chosen cell silhouette and the original prepared vector region.

Do not convert these paths into filled hatches. They are already the geometry the laser should follow, so their LightBurn operation must be Cut/Line mode.

## 7. Build the carrier-layer progression

The Fauxlographic setting is the machine-specific anchor recipe. Rasterizer assumes it represents an approximately **1.00 micrometer pulse pitch**.

Pulse pitch along a scanned path is approximately:

```text
pulse_pitch = speed / frequency
```

When speed is in mm/s and frequency is in kHz, the numerical result is in micrometers. For example:

```text
300 mm/s / 300 kHz = 1.00 micrometer
```

Create `N` carrier layers. In native LightBurn layer order, assign their target pitches evenly from 0.55 to 1.55 micrometers:

```text
pitch[i] = 0.55 + (i / (N - 1)) * (1.55 - 0.55) micrometers
```

If only one carrier layer exists, use 1.00 micrometer.

Clone the tested Fauxlographic setting onto every carrier. Keep its frequency, power, Q-pulse width, pass count, and other machine-specific values unchanged. Remove sublayers, force the operation to Cut/Line mode, and change only the speed according to:

```text
speed[i] = anchor_speed *
           (1 + speed_spread * (pitch[i] / 1.00 micrometer - 1))
```

At the normal `speed_spread` of 1:

```text
speed[i] = anchor_speed * pitch[i] / 1.00 micrometer
```

At a spread of 0, every carrier uses the anchor speed. At a spread of 2, every deviation from the 1-micrometer anchor is doubled.

With 21 carrier layers and a 300 mm/s, 300 kHz anchor, the default progression is 165, 180, 195, and so on through 465 mm/s.

The displayed RGB colors of these LightBurn layers are only identifiers. They do not promise that the engraved surface will show that RGB color.

## 8. Calculate the positional fauxlogram gradient

The fauxlogram gradient chooses which carrier layer receives each cell. It does not draw a visible filled gradient.

First calculate a normalized position `p` from 0 to 1. The bounds used for that calculation depend on scope:

- **Entire artwork:** use the complete artwork bounds. Every color and disconnected shape shares one continuous progression.
- **Each shape:** split the prepared geometry into disconnected components and restart the progression inside each component's bounds.

Direction determines how `p` is measured:

- top to bottom: normalized vertical position;
- bottom to top: one minus normalized vertical position;
- left to right: normalized horizontal position;
- right to left: one minus normalized horizontal position;
- center to edge: normalized elliptical distance from the bounds center; or
- edge to center: one minus that elliptical distance.

Clamp `p` to 0 through 1, then apply the curve:

```text
shaped_position = p ^ gradient_curve
gradient_value = gradient_start
               + (gradient_end - gradient_start) * shaped_position
```

A curve of 1 is linear. Values above 1 hold the result nearer the start value for longer, while values below 1 move away from the start more quickly.

Krasnow Geometry Style can use whole-artwork or per-shape gradients with vertical, horizontal, reversed, and radial directions.

## 9. Add the source-swatch hue offset

For each prepared source-color region, convert its assigned palette swatch RGB value to HSV.

If saturation is below the saturation cutoff, treat it as neutral:

```text
hue_offset = 0
```

Otherwise rotate the normalized hue and apply the inverse control mapping:

```text
rotated_hue = (hue + hue_rotation) modulo 1
hue_offset = 240 - rotated_hue * (240 - 15) - 127
```

Rasterizer's defaults use a hue rotation of 0.13 and a saturation cutoff of 0.2.

Add this hue offset to the positional gradient and clamp the result:

```text
control = clamp(gradient_value + hue_offset, 0, 255)
```

This means two cells at the same position can be sent to different carrier layers when their prepared source swatches have different hues. Low-saturation swatches receive only the positional correction.

## 10. Convert the control value into a carrier layer

For `N` carriers ordered by native LightBurn layer order:

```text
carrier_index = floor(control / 256 * N)
carrier_index = min(carrier_index, N - 1)
```

Move all open line fragments from that cell onto the selected carrier layer.

Repeat for every nonempty cell in every prepared source region. Once complete, join or collect line fragments by carrier layer. Do not union them into filled areas; they must remain linework.

The complete default carrier-selection equation is therefore:

```text
p = directed_position(cell_center, selected_bounds)
G = gradient_start + (gradient_end - gradient_start) * p^curve
H = hue_offset(prepared_region_swatch)
C = clamp(G + H, 0, 255)
layer = floor(C * carrier_count / 256)
```

This is the precise meaning of Fauxlogram Gradient Start and End: they define the beginning and ending **carrier-selection control values** across the chosen scope and direction.

### Worked cell example

Assume:

- 21 non-Black carrier layers;
- a 300 mm/s, 300 kHz Fauxlographic anchor;
- Speed Spread 1;
- a neutral-colored source region, so the hue offset is zero;
- a whole-artwork top-to-bottom gradient from 165 to 90 with Curve 1;
- a cell center one quarter of the way down the artwork; and
- an original-image grayscale sample of 64.

The positional value is:

```text
gradient_value = 165 + (90 - 165) * 0.25 = 146.25
```

The carrier index is:

```text
floor(146.25 / 256 * 21) = 11
```

Counting from zero, carrier 11 of 20 has this target pitch:

```text
0.55 + (11 / 20) * 1.00 = 1.10 micrometers
```

Its layer speed is therefore:

```text
300 * 1.10 = 330 mm/s
```

The luminance-controlled normal angle is:

```text
-90 + (64 / 255) * 180 = approximately -44.8 degrees
```

The actual open paths run perpendicular to that normal, at approximately 45.2 degrees. The cell's paths are clipped to the source vector region and placed on the 330 mm/s carrier layer.

## 11. Optional painted flow regions

Rasterizer's Fauxlogram Flow Painter overrides the shared gradient and angle only inside selected cells. A manual equivalent is possible:

1. Draw one or more region masks over the artwork.
2. Give each region its own start, end, curve, direction, orientation, and reversal.
3. At each cell center, find the topmost region that contains it.
4. Use that region's carrier control and angle instead of the shared settings.
5. Where no region applies, fall back to the shared Krasnow gradient and source-luminance angle.

A region may use a linear guide, radial guide, fixed path orientation, orientation parallel or perpendicular to the guide, or an angle offset. A grayscale image mask can serve as both coverage and guidance: pixels above its threshold activate the region, grayscale value selects progress between the region's start and end, and the local dark-to-light slope determines direction. Flat portions use the region's explicit fallback angle.

Later regions take ownership over earlier regions, but no cell is duplicated. Every cell still produces one set of paths on one carrier layer.

## 12. Export and LightBurn preparation

For SVG output:

- group paths by carrier layer;
- retain open path geometry;
- use layer colors only as stable identifiers; and
- preserve physical scale exactly.

An SVG cannot preserve the laser recipe, so the carrier speeds, frequency, power, Q-pulse width, passes, and other settings must be applied manually after import.

For a LightBurn project:

- create one Cut/Line layer per carrier;
- copy the complete tested anchor setting to each layer;
- remove any sublayers from the carrier copies;
- keep frequency and the other anchor parameters fixed;
- enter the calculated speed for each carrier;
- keep preserved Black on its ordinary Black setting, if used; and
- retain Order by Layer while disabling the other cut-path optimizations for dense generated geometry.

Before engraving, inspect the actual layer settings. Never assume that an organizational layer color predicts the physical result.

## Manual workflow in a vector editor

For a small demonstration that can genuinely be made by hand:

1. Use simple artwork with one or two closed color regions.
2. Place the original raster beneath the vectors and lock it.
3. Draw a 0.4 mm square grid from the artwork's top-left origin.
4. Intersect each relevant grid square with each source vector region.
5. At every occupied square center, record:
   - original-image grayscale value;
   - assigned source-swatch hue and saturation;
   - normalized position in the artwork or component; and
   - the resulting carrier index.
6. A spreadsheet can calculate angle, gradient, hue offset, carrier index, pitch, and layer speed from those recorded values.
7. Create a parallel line array at the calculated path direction and visible spacing.
8. Clip the array to the source-region/cell intersection.
9. Move the resulting open paths to the calculated carrier layer.
10. Repeat for every occupied cell.
11. Apply the calculated LightBurn settings to the carrier layers.
12. Engrave a small test and inspect it under a repeatable directional light from several viewing angles.

This procedure is intentionally practical at small scale and intentionally tedious at large scale. Rasterizer automates the repeated sampling, clipping, grouping, and layer construction; it does not remove the need for a valid physical calibration.

## What each major control really changes

| Control | What it changes | What it does not directly change |
|---|---|---|
| Patch Size | Cell scale and number of local samples | Carrier pitch |
| Cell Shape | Cell boundary and whether deliberate gaps remain | Source color mapping |
| Angle Minimum / Maximum | Brightness-to-orientation mapping | Carrier layer |
| Line Spacing | Visible distance between vector paths | Microscopic pulse pitch |
| Hue Line Spacing Minimum / Maximum | Visible path density by prepared swatch hue | Carrier speed |
| Gradient Start / End | Carrier-selection control at gradient endpoints | Line angle or cell size |
| Gradient Curve | Rate of carrier progression between endpoints | Endpoint carrier values |
| Gradient Scope / Direction | Coordinate system used for carrier progression | Source-luminance sampling |
| Hue Rotation | Hue-derived carrier offset | Visible region color |
| Saturation Cutoff | Whether hue affects carrier selection and visible hue spacing | Laser saturation |
| Speed Spread | Departure of carrier speeds from the anchor | Visible vector spacing |
| Preserve Black | Whether source Black remains ordinary geometry | Non-Black gratings |

## Where Krasnow Geometry Style runs

A compatible Image Style first creates and modifies the vector regions; Krasnow Geometry Style then replaces those finished regions with grating cells. Select No geometric effect when minimal image transformation is desired before that final geometry stage.

Geometry Style can also be routed by swatch, allowing some source colors to remain ordinary vectors, some to become glyphs or Halftone Newsprint, and some to become Krasnow gratings. Before those transformations, overlapping source regions are made mutually exclusive so a point is engraved by only one routed geometry type.

## Physical calibration and limitations

The formulas organize geometry and extrapolate carrier speeds. They cannot prove that a given machine and material will produce the intended diffraction response.

Actual behavior depends on at least:

- laser model and pulse behavior;
- lens and spot size;
- focus position;
- material alloy, finish, and brushed direction;
- cleaning and preparation;
- anchor power, frequency, Q-pulse width, speed, and passes;
- incidence angle and character of the light source; and
- viewing angle and distance.

Start with a small carrier test. Confirm that the anchor actually behaves like a useful 1-micrometer reference, verify that every calculated speed is within the machine's safe limits, and inspect the result under the lighting and viewing arrangement intended for the final piece.

The essential manual recipe is simple to state:

> Divide prepared vector regions into aligned cells, use original-image brightness to orient parallel open paths, use source-swatch hue plus a spatial correction gradient to assign each cell to a calibrated pulse-pitch layer, and engrave those layers with a fixed-frequency speed progression derived from one tested Fauxlographic anchor.

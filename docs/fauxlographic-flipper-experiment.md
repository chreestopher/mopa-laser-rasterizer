# Fauxlographic Flipper experiment

## Goal

Test a two-view angular engraving: from one side the viewer should perceive the uploaded image; from the other side, its horizontally mirrored version. This is directional diffraction, not a true hologram. The center view may show both images at once, and diffuse light may obscure the flip.

## Phase 1: prove directional isolation

The Experimental Laboratories page links to the paired-direction mode in Fauxlographic Etching Lab. Select a tested Material Library setting, set Grid experiment to **Fauxlographic Flipper paired-direction test**, and keep the suggested 45°/135° starting pair or enter two angles from a prior calibration. Columns sweep fill interval; alternating rows repeat the two angles. The mode requires Fill cut mode and disables extra laser-setting sweeps so the comparison changes only direction and interval. The output includes an SVG, a LightBurn project with the selected laser settings copied to every cell, and calibration metadata.

Engrave a small test under stable focus, material finish, and directional lighting. Photograph or record the same cells from fixed left, center, and right viewing positions. For each interval, compare the adjacent A/B rows: does A dominate on one side and B on the other, consistently across the repeated rows? Note center-view cross-talk and repeat the test after repositioning the piece. Do not infer a successful flip from an on-screen preview alone.

Go forward only when at least one angle/interval pair produces a clear, repeatable brightness reversal. If none does, vary lighting, finish, focus, and interval in a new controlled coupon before investing in image interlacing. The present phase does **not** generate a flipped-image engraving.

## Phase 2: smallest image proof (after the gate)

Start with a 25–40 mm asymmetric black-and-white silhouette or short text—not a photograph. Generate a horizontal mirror from that one uploaded source. Interlace narrow vertical cells or strips, assigning each physical cell to exactly one view and one calibrated directional recipe. Show the original, mixed center, and mirrored interpretation in the UI, but label these as geometric previews rather than optical predictions. Use approximately 0.25–0.5 mm strips initially, subject to the calibrated grating spacing and laser spot size.

Export mutually exclusive, registered geometry on two LightBurn layers with the full tested base setting and each view's calibrated angle/interval treatment. SVG-only export can carry the geometry but cannot apply LightBurn laser settings. Validate that LightBurn preserves registration and cut order, and engrave the binary proof before allowing grayscale or photographs. Do not merge both views into a single vector layer, since that would erase the directional distinction.

## Phase 3: evaluate the feature

Only after a binary flip is physically repeatable should the UI accept arbitrary images, offer coverage/brightness balance and view-swap controls, and explore grayscale. Keep the workflow under Experimental Laboratories until the result survives changes in subject matter, position on the work area, and repeat runs. If the physical isolation fails, retain the paired grid as a useful directional-texture experiment rather than claiming a two-view Flipper.

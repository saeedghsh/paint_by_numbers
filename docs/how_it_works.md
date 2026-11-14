# How it works

The conversion is a short pipeline in `src/paint_by_numbers/`. Every step is
plain NumPy or Pillow, so it runs unchanged in CPython and in Pyodide.

1. **Load** (`pipeline.load_image`): honour EXIF rotation, flatten transparency
   onto white, shrink to the profile's *detail* (working resolution, the long
   side in pixels). A lower resolution is itself a simplification.
2. **Restyle** (`styles.py`): an optional artistic filter. Most styles are built
   on a Kuwahara filter (flat patches, crisp edges). `pixel` and `stained-glass`
   also return a *partition* - grid squares or Voronoi cells - whose borders
   are kept as region borders even between equal colours.
3. **Simplify** (`styles.simplify`): edge-preserving smoothing (Kuwahara,
   median) plus a light Gaussian blur that averages away noise, so flat areas
   do not break into speckles.
4. **Reduce colours** (`quantize.py`): k-means in CIE L\*a\*b\*, where distance
   follows perceived difference. Colours closer than ΔE 6 are merged (they are
   hard to tell apart as paints). For a fixed palette (crayon box, acrylic set)
   the clusters are contrast-stretched and matched to *different* crayons where
   the cost is reasonable, so a picture in one colour family keeps its contrasts.
5. **Smooth borders** (`regions.smooth_index_map`): a Gaussian-weighted majority
   vote over colour masks rounds off jagged, noisy borders.
6. **Merge regions** (`regions.merge_regions`): connected areas are found with a
   vectorised union-find. Areas that are too small for the printed size, too
   thin (by erosion depth), or beyond the profile's maximum count join their
   most similar *larger* neighbour, so merging never cycles.
7. **Place marks** (`regions.place_labels`): each number goes at the deepest
   point of its area (the centre of the largest disc that fits, from repeated
   erosion), and long areas get extra numbers by farthest-point sampling.
8. **Render** (`render.py`): colour masks are blurred and enlarged so outlines
   are smooth at print resolution; numbers, dots or shapes are sized to fit
   each area within the profile's limits. The PDF writer (`pdf.py`) embeds
   PNG-compressed pages losslessly, so thin lines and small numbers stay sharp.

## Sizes are printed millimetres

Thresholds are expressed on the printed page (about 270 mm on the long side of
A4 or Letter), not in pixels, so "smallest area: 11 mm" means the same thing
whatever the picture's resolution.

## Age guidance

The presets draw on common developmental milestones; every child is different
and an adult's help is the best adjustment of all.

- **2-3 years**: whole-hand or early tripod grip, scribbling, learning colour
  names; most do not read numbers. Few, very large areas (about 3 cm and up),
  thick lines, colour dots and a pale colour wash instead of numbers.
- **4-5 years**: better control, recognising numbers up to about 10; matching
  shapes. Large areas, up to six colours, numbers printed on coloured dots so
  the colour is still visible; shapes as an alternative.
- **6-8 years**: reads two-digit numbers, can stay inside lines of about a
  centimetre. Ten colours from a 16-crayon box.
- **9-12 years and up**: steadily finer motor control and patience; colours
  come from the picture itself, more areas, thinner lines.
- **Adults**: hundreds of areas, 30-40 colours, thin grey outlines that
  disappear under paint.

`profiles.estimate_difficulty` applies the same bands in reverse: the page is
as hard as its hardest aspect (colours, number of areas, the 10th-percentile
area size when printed, or the need to read numbers).

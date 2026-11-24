# Publication figures

Choose **Style** before **Size**. The style sets column widths, Arial, text sizing,
1 pt trace lines and raster resolution. It preserves the trace, peak anchors,
annotation positions, title and axis labels. Custom dimensions remain editable.
Switching samples retains each sample's applied style; choosing another style
reapplies its defaults. **Figure guidelines…** explains the current preset in the app.

## Available styles

- **General:** 90/180 mm starting widths, automatic 7–10 pt lettering based on
  physical layout, and 300 dpi raster output. These are application choices for
  everyday reports, not a submission standard.
- **Analytical Chemistry (ACS):** 84.6/177.8 mm widths, fixed 8 pt lettering and
  1200 dpi raster output. The font size is our readability choice; ACS allows
  smaller text. Allow room for the caption within its maximum figure depth.
  [Current author guidelines](https://researcher-resources.acs.org/publish/author_guidelines?coden=ancham).
- **Chromatography (Elsevier):** 90/190 mm widths, fixed 8 pt lettering and
  1000 dpi raster output. These follow Elsevier's general artwork guidance, with
  8 pt chosen for readability. The Journal of Chromatography A author page was
  inaccessible during this review; its specific exceptions are not verified.
  [Sizing and raster guidance](https://www.elsevier.com/about/policies-and-standards/author/artwork-and-media-instructions/artwork-sizing).

Layout heights and the 2:1/3:1 options are application choices. Presets are editable
starting points, not an automatic compliance certificate. Review the target
journal's current instructions and inspect the final-size export.

## Fonts and scaling

Arial is the preferred plot font. Helvetica, DejaVu Sans and Times New Roman are
also selectable. Arial/Helvetica are supported by several publishers; consistency
and readability at final print size matter more than scaling everything with the
window. [Elsevier font guidance](https://www.elsevier.com/about/policies-and-standards/author/artwork-and-media-instructions/artwork-overview).

**Font (pt)** displays the actual lettering size. **Auto text size** changes it
with General layouts, within a readable range. Journal modes keep 8 pt across
layouts so figures in the same paper match. Turn Auto off and Apply to set a fixed
size yourself. Titles, axes, ticks and peak annotations use the same size and font.
Resizing the application window changes only preview magnification.

The app uses installed fonts and falls back to bundled DejaVu Sans if the requested
font is unavailable. Hover over the Font selector to see the rendered family;
export metadata records both requested and actual families. No Windows font files
are redistributed with the app. PDF embeds the used font subset; SVG keeps editable
text and needs the matching font installed in the receiving editor.

## Export and chromatogram presentation

PDF is the default for crisp vector curves and embedded, editable TrueType text.
SVG is useful for editing; PNG for reports; losslessly compressed TIFF for raster
submission. **Raster DPI** affects only PNG/TIFF. Raster exports are capped at
24 megapixels to bound memory; larger pages at journal DPI should use PDF/SVG,
or a smaller physical layout. Increasing a finished image's DPI cannot restore
detail; export again from the source trace at the required size.

Keep axis names and units, a clear intensity multiplier, simple strokes and a
white background. The app uses no background grid or decorative frame. The former
instrument/function footer is removed from experimental figures; identity remains
in metadata. Clear the Title field if the manuscript caption supplies that context.
Use short peak labels or numbered peaks, with identities and experimental conditions
in the caption; do not imply a compound identity from an unassigned peak.

Signal processing remains unchanged. GC-MS TIC sums mass channels without smoothing
or normalization. The existing FID adapter's minimum subtraction is still disclosed.
Axis limits change the view only; describe processing or selected regions in the
caption. Check peak labels for overlap, especially after changing aspect ratio.

## Axis breaks

**Axis breaks** lets you omit one interval on each axis, independently or together.
Check **Time (min)** and/or **Signal**, enter the interval's endpoints in the
separate **From** and **To** fields, then click **Apply to figure**. The interval
between those values is hidden. Use original signal values before tick-label
scaling: From `2000000` to `8000000` is equivalent to From `2e6` to `8e6`.
Each break must lie strictly
inside the current visible range. Invalid values keep the last valid figure.

A compact, steep diagonal pair with a narrow white clearance marks the X break on the bottom axis and the signal
break on the left axis. There are no marks on absent top/right axes or inside
the plot. Marker angle stays fixed across layouts, following the
[Matplotlib broken-axis example](https://matplotlib.org/stable/gallery/subplots_axes_and_figures/broken_axis.html).
The remaining sections have proportional
widths/heights: a minute or signal unit occupies the same physical distance on
both sides. Tick values remain the original values. Curves stop at each gap;
source arrays, areas and peak anchors are not recalculated. A Y break can remove
part of a peak, so describe omitted intervals in the manuscript caption.

Labels whose anchors are omitted are hidden and retained in the Peak labels list;
the controls show the hidden count. Removing the break restores them. Label text
can be dragged across the complete plot, including between sections. Review
label and arrow placement after changing breaks or dimensions.

**Remove breaks** preserves current limits and labels; unchecking an individual
axis and applying removes just that break. An enabled break requires both From
and To. **Home** removes both breaks and
restores full automatic ranges. With a break present, Pan/Zoom adjusts the outer
limits of the section where the gesture starts; break boundaries remain fixed.
The numeric range controls provide exact limits. Applied settings are per sample
and last for the current session.

PNG, TIFF, PDF and SVG use the same renderer. Their JSON sidecars include both
omitted intervals and which annotations are hidden by a break. Journal presets
do not imply that a particular journal accepts broken axes; verify the target's
requirements for the figure. Drag-to-select breaks and a zoomed inset for small
peaks alongside dominant peaks are planned follow-ups, not current controls.

Developer check (reads the acquisition in place and verifies its file hashes):

```bat
.venv-qt\Scripts\python.exe -m tools.check_axis_breaks --source "D:\Acquisitions\sample.raw" --output build\axis-break-check
```

## Other guidance reviewed

Nature asks for sans-serif lettering, 5–7 pt ordinary text, units on axes, editable
text and embedded TrueType fonts. It discourages decorative elements and grids.
Its smaller lettering requirements are why General is not presented as universal.
To target Nature, use fixed 7 pt and verify its exact dimensions; there is no
Nature-specific preset yet.
[Nature figure specifications](https://research-figure-guide.nature.com/figures/preparing-figures-our-specifications/).

RSC Advances specifies 83/171 mm column widths and 600 dpi or better TIFF, and also
accepts PDF/EPS for conversion. It requires legible text but its 7 pt chemical
structure settings should not be treated as a universal chromatogram rule. Use
custom dimensions for this journal; an RSC preset is not included yet.
[RSC Advances author guidelines](https://www.rsc.org/publishing/publish-with-us/publish-a-journal-article/rsc-advances).

For accessibility, do not rely on colour alone when comparing traces in future
multi-trace views. A dark monochrome line works for the current single trace.
[Elsevier accessibility guidance](https://www.elsevier.com/about/policies-and-standards/author/artwork-and-media-instructions).

Guidance reviewed September 19, 2026. This covers figure preparation; it does not
validate scientific interpretation or every requirement of a manuscript submission.

## Developer verification

The real-source check exercises all three styles and five layouts, physical vector
dimensions, embedded PDF fonts/editable text, TIFF size/DPI and retained signal and
annotation anchors. It independently rasterizes PDF/SVG and verifies input hashes.
Its 200 dpi PNGs are inspection previews, not journal submission files.

```bat
.venv-qt\Scripts\python.exe -m tools.check_publication --source "D:\Acquisitions\sample.raw" --output build\publication-check
```

Keep the output private and outside acquisition folders. Automated offscreen checks
are distinct from manual desktop and clean lab-PC verification.

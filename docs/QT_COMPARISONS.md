# Chromatogram comparisons

Load two or more GC-MS or GC-FID chromatograms, then choose **Compare samples…**
above the opened-sample list. Check the desired samples, drag rows to change their
order, select **Overlay** or **Stacked**, and choose **Create comparison**. Search
filters the chooser; previously checked hidden rows remain selected and the
selection count discloses them. Clear unchecks all rows. Pending/failed loads,
mass spectra and existing comparisons are excluded.

Each report compares one instrument and compatible signal quantities. Synthetic
examples are kept separate from experimental acquisitions. Each selected trace
retains its own source, MS function, time grid and original signal values. The
renderer does not align retention times or resample. Optional [smoothing and
normalization](QT_PROCESSING.md) are off by default and apply independently to
each source. Both modes share linear time and displayed signal scales; normalized
heights compare relative patterns instead of absolute signals. Negative signals
are retained. A sample outside the
chosen time range has an empty section; data from other samples can remain visible.

The comparison appears as a new item in the left list. Individual reports keep
their settings and annotations. Removing an individual sample from that list does
not invalidate comparisons already created from it. Comparison membership/order
is fixed when created; make another comparison to change its members.

## Report controls

- **View:** switch between overlaid lines and stacked panels. Switching to stacked
  may increase figure height to fit the sample labels and panels.
- **Trace / Label / Color:** select a member and change its display name or color.
  Names are initially numbered to distinguish duplicates; source/function identity
  is retained even when a display name changes. Label/color changes apply directly.
- Existing title, axes, publication/font/layout, numeric ranges, line width, DPI
  and axis-break controls apply to the whole comparison.
- Compact layouts that cannot fit the traces and labels produce an explanation
  and preserve the previous valid figure. Increase Height or use fewer traces.
  Journal presets remain starting points; the requested number of panels can need
  a taller figure than a preset's default.
- Annotate by clicking the nearest visible trace in an overlay or the desired
  stacked panel. The label stays attached to that source trace and can be edited
  or dragged. Pan/zoom updates the shared ranges. Home restores the full view and
  removes breaks. Manual labels are specific to this report.

Stacked panels have visible left axes, with one shared bottom time axis. A time
break is marked on that bottom axis; signal breaks are marked on each visible
left axis. There are no marks on hidden top/right axes. Time and signal gaps hide
only the view and do not alter exported numeric data.

## Export

**Export figure…** writes PNG, PDF, SVG or TIFF using the same renderer as the
preview. Its JSON sidecar records each trace's source/function, point count,
checksum, original metadata, display name/color, report settings and annotation
anchors, plus explicit processing and normalization denominators. PDF embeds
fonts and SVG retains editable text.

**Export data…** writes a long-form CSV: `trace_id`, retention time and signal.
The JSON sidecar maps each one-based ID to its sample/source/function. Every point
is retained, even when samples have different time grids or portions are hidden
by figure limits/breaks. Figure processing does not modify CSV values and is
recorded separately in its metadata. IDs follow comparison order. The CSV contains numeric IDs
instead of untrusted sample names in cells. Original acquisitions are protected
from overwrite across all comparison members.

Settings and comparisons remain session-only. Export before closing the app.

## Developer checks

```bat
.venv-qt\Scripts\python.exe -m unittest tests.desktop.test_comparison -v
.venv-qt\Scripts\python.exe -m tools.check_comparisons --output build\qt-comparisons\source
```

The comparison checker also runs in the packaged app's explicit smoke mode. It
covers both views, all figure formats, numeric/source metadata, state preservation,
and independent PDF/SVG inspection. Use `--ms-source` twice with real acquisition
directories for an optional read-only comparison check. Synthetic PENX cases and
existing parser tests do not establish vendor equivalence or real-FID acceptance.

# Signal processing and relative intensity

The **Signal processing** controls at the top right apply immediately to the
active report. Every new report starts in **Original units**, with smoothing
**Off**. Individual reports and comparison reports keep independent settings.

- **Maximum = 100%** divides each chromatogram by its own full-trace maximum
  after smoothing, then multiplies by 100. It helps compare shape and relative
  peak patterns; normalized heights do not compare absolute signal amounts.
- **Smoothing** uses a centered moving average with an odd window of 3–21
  points. At the beginning/end it averages only available samples, without
  padding with zeros. A window longer than a short trace still uses the available
  samples. Windows count points, not minutes, including on irregular time grids.
  Smoothing can change peak heights, widths and apparent resolution.
- For mass spectra the scale option reads **Base peak = 100%** and the axis
  reads **Relative intensity (%)**. Smoothing is disabled: adjacent m/z channels
  are never averaged together. Counts remain available by choosing Original units.

The order is smoothing, then normalization, over the entire trace. Zoom, axis
breaks and figure dimensions do not change the denominator or smoothing. No
resampling, retention-time alignment or extra baseline subtraction occurs.
An all-zero trace remains zero; mixed positive/negative data keep their negative
values. A nonzero trace with no positive maximum cannot be normalized, and the
control reports this while preserving the previous view.

Changing either option resets the **Y range** to automatic and removes the **Y
break**. This avoids carrying count-based limits into a percentage view or hiding
newly smoothed peaks. Time limits, time breaks and annotations remain. New Y
limits/breaks use the displayed signal after processing, before tick formatting.
Normalized axes use an explicit percent label; the custom original-unit label
returns when switching back. Annotation anchors follow the processed value at
the original sample index. Home restores the full view without turning processing
off; Reset report + labels restores original signal and removes annotations.

For comparisons, the same processing choices apply to each source independently,
retaining its original time grid. Overlay and stacked modes share the displayed
signal scale. Creating a comparison starts with processing off, regardless of the
settings in the individual source reports.

## Exports

PNG, PDF, SVG and TIFF match the processed figure. The JSON sidecar records the
window, edge handling, operation order, per-trace normalization denominator,
display-signal checksum and both original/displayed annotation values. Processing
is shown in the app controls/status; there is no additional plot footer. Describe
any processing in the figure caption or experimental methods when publishing.

**Export data…** still exports every original value of the selected trace (TIC,
EIC, single/averaged spectrum), including values hidden by ranges/breaks. Figure
smoothing and normalization do not change CSV values. The JSON records active
figure processing separately and explicitly says it was not applied to the CSV.
The existing spectrum CSV relative-intensity column remains calculated from the
original spectrum. Processed/ranged numeric exports are separate future work.

## Developer checks

```bat
.venv-qt\Scripts\python.exe -m unittest tests.desktop.test_processing -v
set QT_QPA_PLATFORM=offscreen
.venv-qt\Scripts\python.exe -m tools.check_processing --output build\qt-processing\source
```

The checker covers individual/comparison/spectrum figures, all four figure
formats, original CSV preservation and independent PDF/SVG rendering. Pass
`--ms-source` twice for two real acquisition directories to additionally exercise
real TICs, an EIC and an averaged spectrum and verify unchanged acquisition hashes.
It also runs with synthetic data in the standalone package smoke test.

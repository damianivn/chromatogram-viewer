# GC-FID reader and calibrated units

Open TotalChrom **type-1 PENX `.raw` files** through Open GC-FID or the sample
library. The same strict reader is used for both. GC-MS still uses `.raw`
directories and the existing pinned rainbow fork.

The app uses the integrated TotalChrom reader in `gcviewer.parsers.totalchrom`,
derived from `tcfid` 0.3.1, with the bounded reader checks recorded in
[adoption notes](tcfid/ADOPTION.md). It walks the variable-length header and reads
the declared signed integer array. Point count and stored extrema must match.
Footer values are never scanned as signal. Invalid or unsupported files show a
load error; there is no fallback to guessed offsets or a guessed sampling rate.

## Time, signal and exports

- Point `i`, starting at zero, occurs at `delay_min + (i + 1)/(60 × rate_hz)`.
  The first point is one sampling interval after the recorded delay.
- Original integer counts remain read-only in memory. Signal is calibrated using
  the file's channel scale: `µV = counts/(scale × multiplier)`. There is no minimum
  subtraction. Negative values are retained.
- **Readable units** displays the default Response axis in **mV**. Data, custom
  ranges and break endpoints stay in **µV**: 1000 µV = 1 mV. Controls state this.
  Plain/scientific number styles use µV; normalized figures use percent.
- **Export data** retains all calibrated µV values, irrespective of smoothing,
  normalization, zoom or breaks. This CSV is a calibrated trace, not a peak-area
  table. Its JSON and figure sidecars include the source SHA-256, parser version
  and reader revision, recorded header, count checksum, rate, scale, point count,
  clipping count and warnings. Figure metadata also records tick-unit conversion.
- The worker carries original counts and typed acquisition metadata separately
  from the figure. These survive switching samples and presentation edits, and
  are released when their sample is removed. The [FID Analysis view](QT_FID_ANALYSIS.md)
  uses them for single-run peak integration and analytical reports.

An incomplete-file flag, unverified format version or inconsistent recorded run
duration is shown as a warning. The known A/D ceiling is also disclosed when
clipping is detected. Structural corruption, missing channel calibration and
invalid timing/scale are errors. A file visible in the library has passed a cheap
type check, not full decoding; errors are reported when it is opened.

## Appearance

The workspace uses native Qt controls and the platform UI font, following the
supplied FID applet. Custom blue sample-list styling and heavy group-box overrides
were removed, compact single-line sample rows are retained, and the navigation
toolbar sits above the plot. Publication figure dimensions/fonts are unchanged.
Offscreen checks load Segoe UI from Windows when available, otherwise the bundled
DejaVu Sans font; this does not install fonts or change system settings.

## Verification and limits

Local synthetic PENX fixtures exercise varied header sizes, exact array limits,
signed counts, non-default rates/delays/scales, corruption and worker/export
round-trips. They are **structural tests, not vendor-output comparisons**.
The supplied project's vendor checks have been retained under `tests/fid_core/`.
They need external RAW/RAX/RST files via `TCFID_TEST_DATA`. Three additional
RAW/RST pairs and their printed PDFs have now been compared (15 peaks); measured
differences are recorded in the analysis guide. The original RAW/RAX corpus and
broader instrument acceptance remain pending.

The supplied evidence concerns TotalChrom 6.3.2 / Clarus 500, principally channel
A and format 10019. Other versions are unverified; channels without valid scales
are rejected. The clipping ceiling is based on that instrument evidence. The
original development notes describe broader scientific limitations.

```bat
.venv-qt\Scripts\python.exe -m unittest tests.desktop.test_fid_reader -v
.venv-qt\Scripts\python.exe -m unittest discover -s tests/desktop -v
.venv-qt\Scripts\python.exe -m unittest discover -s tests -v
```

Historical figures/CSVs produced by the old heuristic reader can differ in both
units and retention time. Reopen the original acquisition to make corrected
exports; do not compare old raw-count values directly with calibrated µV.

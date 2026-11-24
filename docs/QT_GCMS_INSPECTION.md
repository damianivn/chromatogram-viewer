# GC-MS inspection in Qt

Open a GC-MS acquisition through the sample library or **File → Open → GC-MS acquisition…**, select
its loaded trace, then choose **Analysis → GC-MS inspection / EIC…**. Choose the **MS
function** explicitly. Only validated functions with detector `MS` are offered;
invalid functions are reported in the preview notes.

Choose a view:

- **Total ion chromatogram:** sum all recorded mass channels for each scan.
- **Extracted ion chromatogram:** enter the requested m/z, then **Update preview**.
  The nearest recorded channel is extracted, with the requested and actual m/z
  shown below the plot. Ties choose the lower channel. This is one channel, not
  a mass tolerance window, integrated band, or interpolated mass. Requests
  outside the recorded mass range are rejected.
- **Single-scan spectrum:** enter a time in minutes. The nearest recorded scan
  is used; ties choose the earlier scan. The actual time is disclosed.
- **Averaged spectrum:** enter **From** and **To** in minutes. The arithmetic mean
  includes only scans within that closed interval, weighted equally. The actual
  first/last scan times and scan count are disclosed. Empty, reversed, non-finite
  and out-of-range intervals are rejected without replacing the last valid preview.

All views use original counts, with no smoothing or normalization. The averaged
spectrum deliberately uses exact interval membership; the older Streamlit view
rounds both interval endpoints to nearby scans. Their results can differ when
an entered boundary falls between scans. Single-scan and EIC nearest-selection
behavior follows the existing application.

Click **Create report** to add the selection to the compact sample list. The
original chromatogram and its report settings/labels remain available. Spectra
use independent vertical mass sticks and an m/z axis; chromatograms use retention
time. The usual publication presets, annotations, axis breaks, pan/zoom and
PDF/SVG/PNG/TIFF exports work on the new report. Use **GC-MS tools…** again to
create another selection. Report settings remain session-only.

**Export data…**, below the plot, writes a full-resolution CSV and a `.csv.json`
sidecar. Chromatograms include retention time and signal; spectra include every
mass channel (including zero channels), counts and an additional base-peak-relative
percentage column. Counts in the plot and CSV are unchanged. The percentage
column divides by the largest positive intensity; it is all zero if there is no
positive base peak. Axis ranges and breaks never crop numeric exports. The
sidecar records the source, function, requested/actual selection, processing,
point count and checksum. Acquisition folders are protected from export writes;
existing export/sidecar files require replacement confirmation.

Bulk loads continue to retain small TIC arrays. Opening GC-MS tools reads the
mass matrices on demand in an owned background worker and pauses the pending
bulk queue. An already-running acquisition may finish. Closing the dialog frees
the matrices and resumes the queue; only the selected 1D report remains. No raw
acquisitions are copied into the application package.

## Verification

The automated suite uses known synthetic matrices for arithmetic, validation,
channel/scan choices, transport, zero channels, exports, spectrum breaks and Qt
state preservation. The opt-in real-data check compares the inspector's results
against the patched parser's arrays/TIC/EIC helpers, tests the actual owned worker,
exports all four figure formats plus CSV, and verifies acquisition file hashes.
This is internal consistency evidence, not a comparison against vendor exports.

```bat
set MPLCONFIGDIR=build\matplotlib-cache
set QT_QPA_PLATFORM=offscreen
.venv-qt\Scripts\python.exe -m unittest tests.desktop.test_ms_inspection -v
.venv-qt\Scripts\python.exe -m tools.check_inspection_ui --source "D:\Acquisitions\sample.raw" --output build\ms-check
.venv-qt\Scripts\python.exe -m tools.check_package --exe dist\ChromatogramViewer\ChromatogramViewer.exe --ms-source "D:\Acquisitions\sample.raw" --output build\ms-package-check
```

Keep check outputs outside acquisition folders. The executable remains in the
existing `dist/ChromatogramViewer` folder. Native/high-DPI interaction, clean
restricted lab-PC transfer and vendor-reference comparisons remain separate
acceptance checks. Multi-trace overlays/stacks and optional processing are later
migration work; the previous Streamlit application remains in the separate
original repository, outside this Qt-only project.

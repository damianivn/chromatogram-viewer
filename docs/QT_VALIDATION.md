# Qt prototype validation — September 17, 2026

Historical checkpoint. The September 19 sample-library stage and real GC-MS
checks are recorded in [QT_SAMPLE_LIBRARY.md](QT_SAMPLE_LIBRARY.md).
Statements below about keeping Streamlit in the same checkout describe the
initial evaluation only. Since September 21, `gcviewer` is Qt-only; the previous
Streamlit app lives in the separate original repository.

Status: **ready for review**, with manual and real-acquisition checks pending.
This records executed checks, not a release certification. Reproduction commands
and controls are in [QT_PROTOTYPE.md](QT_PROTOTYPE.md).

## Source and automated checks

- **8/8 existing SPL tests passed, no skips**, in both the original chemistry
  environment and the isolated Qt environment. The supplied fixture was present.
- **16/16 separate desktop tests passed** in 11.642 s. Coverage includes array
  validation, empty ranges, flat/short traces, signal preservation, annotation
  anchors and moved positions, all export formats, dimensions, vector elements,
  overwrite/input protection, rainbow function eligibility, input-type errors,
  PENX disclosure, Qt click/drag/edit, sample switching/reset, late-load identity,
  close during function selection, worker termination and errors.
- A generated PENX byte stream exercised the actual parser in an owned process:
  1,200 ramp points, known minimum-subtracted output. This is an explicitly
  synthetic parser fixture, **not a real acquisition**. GC-MS tests use installed
  rainbow `DataFile`/`DataDirectory` objects with multiple MS functions and UV.
- Dependency consistency, source compilation and new-file whitespace checks
  passed. Existing Streamlit app/applets/parsers/helpers/requirements/launchers
  were not edited. The local spreadsheet SHA-256 remained unchanged.
- Qt emitted an upstream high-DPI API deprecation warning; suite shutdown emitted
  one GC ResourceWarning. Neither failed a test. Actual loader subprocesses were
  verified stopped on close; no owned app processes were left running.

## Figure inspection

`python -m tools.check_exports --output build\qt-evidence` drove Qt mouse
gestures to add and move three labels, changed the title and both axes, and set
**160 × 100 mm at 200 DPI**. It produced PNG/PDF/SVG and JSON sidecars, then
rasterized the vector files independently with QtPdf and QtSvg. All outputs and
the 1280 × 820 / 1024 × 768 workspace screenshots were visually inspected.

The changed text and moved labels appeared in each format, with anchors attached
to the same samples and no missing labels or clipped plot in this example. PNG is
**1259 × 787 pixels**. PDF page dimensions matched physical size, PDF had no image
objects, and SVG contained paths and no image elements. Label anchors/positions
and settings matched in sidecars. Small text-edge, font-width and line-rendering
differences were visible; the formats are not pixel-identical.

At the PNG resolution, mean absolute RGB-channel error on a 0–255 scale was
**2.6219 for the PDF render** and **2.6216 for the SVG render**; about **2.37%** and
**2.36%** of pixels differed by more than 32 in any channel. Preview versus PNG
resampled to the preview's 732 × 458 pixels had mean error **4.4641**. These are
descriptive measurements, not scientific accuracy or perceptual-quality scores.

The first offscreen screenshot showed unavailable default UI fonts. Explicitly
loading Matplotlib's bundled DejaVu Sans corrected the UI glyphs. Final inspected
screenshots use that font. Very long text and other extreme size/font combinations
still require visual checking by the person preparing the report.

## Windowless launch and packaging

Environment: Windows 11 build 26200, Python **3.12.13** bootstrapped from the
existing Conda interpreter into `.venv-qt` with system site packages disabled.
PySide6 **6.11.2**, Matplotlib **3.11.2**, NumPy **2.5.3**, SciPy **1.18.1**, pandas
**2.3.3**, rainbow-api **1.0.11**, PyInstaller **6.22.3**, hooks **2026.7**. The full
lock file records dependencies and the verified fork archive's revision/hash.
No global/shared Python packages or global settings were changed.

The exact build command was:

```bat
.venv-qt\Scripts\python.exe -m PyInstaller --noconfirm qt_prototype.spec
```

The final one-folder, windowless build succeeded at
`dist\ChromatogramViewer\ChromatogramViewer.exe`. Its folder totals
**288,295,727 bytes (about 275 MiB)**. Executable SHA-256:

```text
27FF626E504E471F55C90963078BD788BA30917EC2E400AD1CA6CC4191D5C19C
```

Two build issues were found and repaired before delivery. The first build lacked
seven DLLs needed by the Conda base interpreter; the spec now collects those
existing files conditionally. A subsequent packaged smoke exported PNG but timed
out before PDF because the restricted Matplotlib hooks had omitted PDF/SVG
backends. Both backends are now explicit. The final build had no unresolved DLL
warnings; an optional `scipy.special._cdflib` hidden-import warning remains. The
used parser/export paths passed their packaged checks.

Executed launch results:

- Source `pythonw -m gcviewer.desktop --smoke-output …`: exit **0**.
- `wscript.exe launch_qt.vbs /smoke-output:build\vbs-user-smoke`: exit **0** under
  the normal user account. The initial sandbox WScript attempt was stopped after
  a timeout; CScript reported denied settings access there. No Windows policy or
  registry setting was changed to run the successful check.
- Final `tools.check_package` ran the executable from a temporary directory,
  removed Python environment overrides and restricted PATH to Windows folders.
  Synthetic GUI plus PNG/PDF/SVG export/shutdown: exit **0**, **8.328 s**.
  Generated PENX worker: exit **0**, **12.390 s**. Empty MS directory: expected
  error exit **1**, **2.172 s**, with structured error evidence.

These timings include startup/import work and are single smoke observations.
They do not measure large acquisitions or establish responsive loading on lab
hardware. All launch smokes were **offscreen**. An automated launch through the
real VBS script is still not a human double-click or native-dialog test.

## Evidence availability and next review

Locally generated screenshots/exports are in ignored `build\qt-evidence` and
`build\package-final-evidence`. A handoff copy is kept outside Git in the sibling
work folder, `artifacts\001-qt-prototype`, along with the final build warnings,
environment lock and package checksum. These files and the `dist` package are
local-only; they were not committed, uploaded or published. Copy the evidence
explicitly if transferring the review, and copy the entire package folder to
try the executable elsewhere.

Still unverified:

- Real GC-MS function selection and TIC correctness against vendor output;
  real PENX boundaries, retention time, signal and sampling-rate interpretation.
- Native open/save dialogs, overwrite confirmation, human label dragging,
  multiple-monitor/high-DPI behavior, long real sample names, and closing during
  a real slow acquisition load.
- Startup and all dependencies on a clean restricted lab account without Python,
  offline installation from a wheel bundle, and large-file memory/latency.

The prototype supports continuing the Qt evaluation for direct figure editing.
The evidence does **not** support a permanent migration decision yet. Streamlit
remains the broader working viewer, including spectra, EICs, comparisons and SPL
workflows that are deliberately outside this prototype.

# Qt desktop workspace (development build)

This Windows-oriented PySide6 + Matplotlib app is the application in the
Qt-only `gcviewer` repository. The previous Streamlit viewer lives in the
owner's separate original repository. This is a development build, not a
scientifically validated release. It opens with an empty workspace and prompts
you to open acquisition data. Synthetic signals are used only by explicit developer checks.
The first migration stage adds the [sample library](QT_SAMPLE_LIBRARY.md).
GC-MS tools now add [EICs, single-scan/averaged spectra and numeric exports](QT_GCMS_INSPECTION.md).
GC-FID has a separate [Analysis tab](QT_FID_ANALYSIS.md) for single-run
integration, saved methods/layouts, peak tables and PDF reports.
See also the [loading, axes and navigation refinements](QT_REFINEMENTS.md).
For style presets and the journal guidance behind them, see
[publication figures](QT_PUBLICATION_FIGURES.md).

## Set up and open

Use an existing **64-bit Python 3.12** installation. No administrator rights or
global package changes are needed. Setup does not download Python.

From the application folder in Command Prompt:

```bat
setup_qt.bat "C:\Path\To\Python312\python.exe"
```

Or create the environment explicitly:

```bat
"C:\Path\To\Python312\python.exe" -m venv .venv-qt
.venv-qt\Scripts\python.exe -m pip install -r requirements.txt
```

Then **double-click `launch_qt.vbs`**. The application runs without a terminal.
VBScript/Windows Script Host must be allowed by the PC's policy. If it is disabled,
use the packaged executable described below. Missing-environment errors appear in
a message box. Python failures show a message and append a diagnostic log to
`%LOCALAPPDATA%\ChromatogramViewer\qt-startup.log`; abrupt native-library crashes
may only produce the launcher's exit-code message. Debug command:

```bat
.venv-qt\Scripts\python.exe -m gcviewer.desktop
```

The isolated environment is machine-local; do not copy `.venv-qt` to a lab PC.
The default `install.bat`, `run.bat` and `requirements.txt` now target Qt.
`run.bat` is the console launcher; `launch_qt.vbs` is the windowless source launcher.
The sample library supports PE Jet-3 SPL lists. The SPL parser preserves
the original filename as metadata for accurate matching. The app's Matplotlib
cache uses the temporary directory, separate from the user's configuration.
The historical filenames `QT_PROTOTYPE.md` and `qt_prototype.spec` remain valid
so existing guide links and build commands keep working.

## Workspace and appearance

Choose **View → Figure** (Ctrl+1) or **View → FID Analysis** (Ctrl+2).
The latter becomes available when a GC-FID acquisition is selected.
**Analysis → Compare samples** creates a comparison in Figure view.
The plot heading identifies the current view and sample. There is no duplicate
global shortcut toolbar; local Home/Pan/Zoom controls sit immediately below the plot, followed by the sample heading and notices. FID Analysis has compact Integrate and PDF report actions above its plot.
Figure controls are grouped into **Style**, **Axes**, **Labels**
and, for comparisons, **Traces** in the right inspector. Less-used font/output
settings expand under **Typography and output**. Apply figure settings after
editing. FID methods and names sit in the inspector, with timed
events collapsed under **Advanced** and peak results below the plot.

Use **File → Open / Export** and **Analysis** for loading, integration, methods,
report layouts and reports. Drag pane dividers to resize; the **View** menu can
hide the browser, inspector or analysis results. **Reset workspace arrangement**
restores their visibility and default proportions.

**Edit → Preferences** or **View → Appearance** offers **System**, **Light** and
**Dark**. The appearance choice is remembered for this Windows user.
Controls, menus, highlights and editors share compact rectangular styling in
all modes, with neutral selections and visible focus outlines. System follows
the operating system's color scheme while retaining the same control geometry.
Figure/export paper stays white in all themes. These preferences do not save
loaded samples or session edits across closing the application.

## Try the figure workflow

Use **Sample library…** to browse a parent acquisition folder, optionally choose
a PE GC-MS `.SPL` list, search/sort/select rows and **Open selected**. See the
[sample-library guide](QT_SAMPLE_LIBRARY.md) for queue controls and matching rules.

1. Open an acquisition and select its loaded trace in the sample list. Plot and
   export controls become available once a trace is ready.
2. Choose **Style**, then **Size**, or edit **Width / Height (mm)**; these update
   immediately. **Auto text size** adapts General lettering to the layout and keeps
   journal lettering consistent. Turn it off to set **Font (pt)** manually. Edit
   title, axis labels, font family, line size, color and **Raster DPI**, then click
   **Apply to figure**. Ranges use `minimum, maximum`; a blank
   field means Auto. Invalid or empty time ranges preserve the last valid figure.
   Settings not yet applied are discarded when switching samples; Export applies
   the current controls before opening its save dialog.
3. With **Annotate** checked, click a data location. The label anchors to the
   closest recorded time point. Click its text to select it, then drag the label
   away from crowded peaks. The connecting line stays attached to the original
   data point. Edit text in **Peak labels**, then Update or Enter. Delete removes
   the selected label; Clear removes all labels for this sample.
   **Automatic labels…** labels the top N peaks or peaks above a percentage of
   the full-trace maximum. Detection uses the displayed signal (including any
   selected smoothing/normalization); prominence controls sensitivity. It is a
   figure tool and does not integrate peaks or change acquisition values.
   For an individual FID sample with current integration, choose its integrated
   peaks and assigned names instead, with retention times, names, or both.
   Names-only skips unassigned peaks; both uses retention times for unnamed peaks.
   Comparison figures can detect labels on a chosen trace.
   Only anchors in the retained view are selected. Text is initially arranged
   to reduce overlap; crowded figures may need fewer labels or manual dragging.
   **Show selected label** hides/restores a label in the preview and exports.
   Generate again to refresh names/settings: it replaces automatic labels on the
   chosen trace, including edits to those labels, and preserves manual labels.
   Labels are snapshots, not live chemical identification or numerical results.
4. **Axis breaks** accepts one optional interval per axis: check **Retention time (min)** (or **m/z** for a spectrum)
   or **Signal**, fill its separate **From** and **To** fields, then **Apply to
   figure**. Values between those endpoints are hidden. Both axes can be used
   together. Signal uses original units, even when ticks show billions: From
   `2e9` to `8e9` skips two to eight billion. Uncheck an axis and Apply to remove
   just its break. **Remove breaks** immediately restores the
   continuous view without deleting labels. See [axis-break details](QT_PUBLICATION_FIGURES.md#axis-breaks).
5. Pan and Zoom turn off annotation gestures. Their axis ranges also apply to
   exports. With breaks, they adjust the selected section's outer limits while
   keeping break boundaries fixed. Use the numeric ranges for exact control.
   **Home** restores automatic ranges and removes both breaks. Turn Annotate on
   to edit labels again.
6. Open another acquisition. Switching samples preserves each
   sample's applied report settings and labels. **Reset report + labels** restores
   the report preset for the current sample. State is session-only.
7. **Export figure…** starts with PDF and also offers SVG, PNG and TIFF. Select the format and filename;
   existing figures **or sidecars** require confirmation. The accompanying
   `filename.png.json` (or `.pdf.json` / `.svg.json`) records source path, sample,
   selected function, parser metadata/warnings, transformations, trace checksum,
   dimensions, ranges, omitted intervals and exact label anchors/text positions. Save outside all
   `.raw` acquisition directories. Acquisition inputs cannot be overwritten.

The preview fits the available space while retaining the chosen page aspect
ratio. PNG/TIFF dimensions are physical inches × DPI, rounded down to whole pixels.
PDF retains vector curves and embedded TrueType fonts; SVG retains editable text
and needs the selected font installed in its viewer. No whole-plot screenshot
is embedded. All formats use the preview's renderer and state. The sidecar
contains the original full source identity even if a sample name is elided in the
list; hover a sample to see its full path. For very long figure titles or labels,
shorten the text or increase dimensions and inspect the exported margins. A long
title is not automatically rewritten. Raster antialiasing and vector font rendering
can differ slightly between viewers. Files are staged before replacement, but the
figure and JSON are two filesystem operations, not an atomic two-file transaction.

### Figure dimensions

In **General** style, the **Size** menu provides these editable starting points:

- **Report:** 180 × 110 mm (the default).
- **Single column:** 90 × 70 mm.
- **Double column:** 180 × 120 mm.
- **Landscape:** 180 × 90 mm, 2:1.
- **Wide:** 180 × 60 mm, 3:1, for a longer chromatogram.

The 90/180 mm widths follow the guideline widths in
[Nature's formatting guide](https://www.nature.com/nature/for-authors/formatting-guide).
Heights and aspect ratios are application choices, not a universal chromatogram
standard; check your journal's instructions. **Custom dimensions** focuses the width
field. Width and height accept tenths of a millimetre; changes apply on Enter or
when leaving the field. Each sample remembers its dimensions during the session.
Changing size preserves its source signal, peak anchors and label positions.

Journal styles substitute their column widths while retaining these layout choices.
The on-screen figure scales to fit the centre panel. Exported PNG/TIFF/PDF/SVG retain
the selected physical dimensions, independent of window size. Narrow and short
layouts reserve space for labels; readable large-number units wrap below the
y-axis title on short pages. Experimental figures have no instrument/function footer;
source identity stays in the sample panel and sidecar. Developer-check synthetic
figures retain their disclosure. Inspect longer custom text before using a figure.

An opt-in check with real acquisitions exercises every preset, export dimensions,
sample switching and compact-list density, and verifies input-file hashes:

```bat
.venv-qt\Scripts\python.exe -m tools.check_layouts --folder "D:\Acquisitions" --spl "D:\Lists\run.SPL" --output build\layout-check
```

Output contains real sample identities and plots; keep it private and outside
acquisition folders. This uses offscreen Qt, not manual desktop verification.

## Real input adapters and scientific limits

- **Open GC-MS folder…** selects one MassLynx/Perkin-Elmer `.raw` **directory**.
  The existing `waters_parser.load_raw` reads it using the required patched
  `damianivn/rainbow` fork. Eligibility uses the installed rainbow API's
  `DataFile.detector == "MS"`, actual filename and validated time/mass/data arrays.
  If multiple usable functions exist, choose one explicitly. **GC-MS tools…**
  can add another function's TIC, EIC or spectrum as a separate report. TIC is the sum across mass
  channels, with `sm=1` and `norm=False`; no implicit smoothing or normalization.
- **Open GC-FID file…** selects one PENX TotalChrom type-1 `.raw` **file**. The
  strict `tcfid` reader preserves signed counts, uses the recorded rate and scale,
  and returns calibrated µV without baseline subtraction. Default readable ticks
  show mV; ranges and breaks use µV, and CSV retains µV. Structural errors stop
  loading instead of falling back to the retired heuristic reader. See
  [FID reader and units](QT_FID_READER.md), including deferred vendor checks.
- Optional [figure smoothing/normalization and relative spectra](QT_PROCESSING.md)
  are explicit and default off. No quantification or compound identification is
  performed. Axis ranges clip only the view; CSV retains original trace values.
  Source arrays are copied, validated and read-only in the model.
- Acquisition parsing occurs in a separate owned process. Results are associated
  with the request's sample, not whichever sample is currently selected.
  The process is reused between files. Clicking a waiting sample promotes it to
  next; the current parse finishes. Remove/cancel or closing the window stops
  that worker and removes temporary results. No acquisition cache survives reopening an input.
- Real private GC-MS acquisitions were read in place during stage 1: all 72
  distinct sources referenced by the real SPL fixture loaded successfully, and
  739 source files were hash-verified unchanged. Those acquisitions are not
  bundled with the app. Real PENX, vendor-export comparisons and large-file
  latency/memory checks remain required. Synthetic PENX and in-memory rainbow
  tests exercise contracts, not instrument accuracy.

## Tests and build

The tested complete environment is captured in `requirements-qt-lock.txt`, including
the build/test tools and the verified rainbow archive revision/hash. For an exact
rebuild, install this lock file into a newly created project-local environment.
The smaller `requirements-qt.txt` is suitable for running the source prototype.

```bat
.venv-qt\Scripts\python.exe -m pip install -r requirements-qt-lock.txt
.venv-qt\Scripts\python.exe -m pip check
.venv-qt\Scripts\python.exe -m unittest discover -s tests -v
set QT_QPA_PLATFORM=offscreen
.venv-qt\Scripts\python.exe -m unittest discover -s tests/desktop -v
.venv-qt\Scripts\python.exe -m gcviewer.desktop --smoke-output build\qt-smoke
set QT_QPA_PLATFORM=
.venv-qt\Scripts\python.exe -m PyInstaller --noconfirm qt_prototype.spec
```

For a build with currently resolved dependency ranges instead of the recorded
lock, install `requirements-qt-build.txt`. Build outputs are ignored in `build/`
and `dist/`. The spec creates a windowless **one-folder** package:

```text
dist\ChromatogramViewer\ChromatogramViewer.exe
```

Copy the **entire** `dist\ChromatogramViewer` folder, including `_internal`, to a
writable folder on a lab PC. Double-click the executable; no Python installation
should be required. That expectation must still be tested on a clean restricted
lab account. Do not copy only the `.exe`. This is a local unsigned evaluation
build, not an installer or release. PyInstaller's
[Qt/Matplotlib hook configuration](https://pyinstaller.org/en/stable/hooks-config.html)
includes QtAgg/Agg plus PDF/SVG export backends and excludes other Qt bindings
and Streamlit. The spec also collects base runtime DLLs when the environment was
bootstrapped from Conda; it does not alter that base installation.

An automated packaged smoke can use:

```bat
set QT_QPA_PLATFORM=offscreen
dist\ChromatogramViewer\ChromatogramViewer.exe --smoke-output build\packaged-smoke
set QT_QPA_PLATFORM=
```

Wait for `smoke-ok.txt` and process exit. This verifies empty startup, then explicitly
injects synthetic fixtures for export/interaction checks and shutdown; it does not
verify native file dialogs or a human drag.
Automated smoke failures write `smoke-error.txt` and exit instead of waiting for
a message box. Use a fresh output directory for each verification.

For an isolated working-directory/package-loader check and export inspection:

```bat
.venv-qt\Scripts\python.exe -m tools.check_package --exe dist\ChromatogramViewer\ChromatogramViewer.exe --output build\package-check
.venv-qt\Scripts\python.exe -m tools.check_exports --output build\export-check
```

The package check removes Python environment overrides, limits PATH to Windows
directories, and exercises an explicitly generated synthetic PENX file, an
empty MS directory, and library discovery with the private reference SPL when supplied via `--spl`.
It still runs on the development PC. Source launcher smoke
without an interactive terminal is available through
`wscript.exe launch_qt.vbs /smoke-output:build\launcher-check` with
`QT_QPA_PLATFORM=offscreen` set for the check.

## Evaluation evidence and comparison

The first validation run passed all **8 existing SPL tests**, without skips, in
both the original chemistry environment and the new isolated environment. The
new suite passed **16 model/adapter/export/Qt tests**: bad arrays/ranges,
flat traces, signal preservation, exact dimensions, vector output, provenance,
input types, function eligibility/choice, moved labels, per-sample state,
background-load identity, worker errors, a generated synthetic PENX round-trip,
closure during function choice and close-time termination. File-dialog
selections in Qt tests are mocked; the offscreen canvas receives real Qt mouse/key
events. The initial offscreen screenshot revealed missing UI fonts, corrected by
loading DejaVu Sans explicitly from Matplotlib's bundled fonts.

Historical build/export inspection results are recorded in `QT_VALIDATION.md`.
Current stage-1 results and reproduction commands are in `QT_SAMPLE_LIBRARY.md`.

Qt offers persistent editing and label dragging within one figure workspace,
connected to a sample library. [Overlay/stacked comparisons](QT_COMPARISONS.md)
are available with shared scales and individual source identities. Optional processing remains
planned work; its earlier implementation is in the separate Streamlit repository. Qt supports
on-demand EICs and single-scan/averaged mass spectra with full-resolution CSV
exports; see [GC-MS inspection](QT_GCMS_INSPECTION.md).
Native dialogs, live dragging, high DPI, vendor-reference accuracy, comparative
performance and startup on a clean non-admin lab PC remain acceptance checks
before a validated student rollout.

Input controls share one outer frame and borderless arrow areas. Focus and pressed/open states change color without moving labels; embedded editors do not add a second frame. Dropdown choices use the same flat neutral selection as other lists. Keep these rules in desktop/appearance.py when adding controls.

# Qt sample library

The Qt sample library provides folder browsing, PE GC-MS sample-list matching
and opening multiple acquisitions. This repository is Qt-only; see
[GC-MS inspection](QT_GCMS_INSPECTION.md) for EICs, spectra and numeric exports.
See [comparison reports](QT_COMPARISONS.md) and [optional signal processing](QT_PROCESSING.md).

## Open samples

1. Launch `launch_qt.vbs`, or the packaged `ChromatogramViewer.exe` inside the
   complete `dist/ChromatogramViewer` folder. See [setup and packaging](QT_PROTOTYPE.md).
2. Click **Sample library…**. Choose GC-MS or GC-FID and the **parent folder**
   containing acquisitions. GC-MS `.raw` inputs are directories; GC-FID PENX
   `.raw` inputs are files.
3. For GC-MS, optionally **Choose list…** and select the supported Perkin-Elmer
   Jet-format `.SPL`. Leave it blank for folder browsing. This support is specific
   to the existing PE format; it does not imply arbitrary Waters SPL compatibility.
   Choosing a list shows its entries only, even if the folder contains thousands
   of acquisitions. **Clear list**, then **Refresh library**, returns to all
   folder acquisitions. The context line shows both counts.
4. **Refresh library**, search names/descriptions/vials/types/methods/statuses,
   or click a column heading to sort. Ctrl/Shift-select rows or **Select all
   available**. Only visible, available rows are opened. Hover for the full path
   and matching rule. Missing and unsupported rows stay visible.
5. **Open selected** sends the selection to the workspace and closes the library.
   Acquisitions load one at a time in a background process;
   browsing and searching the library do not parse signal arrays.
   The process stays ready between files to avoid repeating startup/imports.
   Clicking a waiting sample moves it **next**, after the current parse finishes.
6. Use **Find an opened sample…** in the left panel to search opened/waiting
   samples. Compact rows show filename and load state on one line; hover for
   vial/description, full path and function. Drag the panel divider to resize it;
   expand **Sample details** for metadata.
7. Select a queued/loading sample and **Remove** to cancel it.
   A failed row shows its error; use **Retry** after resolving the
   cause. Closing the workspace stops its workers and discards remaining requests.

Folder/list edits invalidate the old selection until refresh finishes. Discovery
can be cancelled, and refresh preserves selections by their list-row identity.
Reopening the same library row focuses its existing request and preserves report
settings and labels. Individual **Open GC-MS…** still allows another copy/function
of a previously opened acquisition.

The library remembers the last valid acquisition folder across app restarts.
**Choose list…** separately remembers the folder of your last selected SPL;
clearing the active list does not clear that browsing location. Valid manually
entered paths are remembered too. Cancelling a chooser or entering a missing
path keeps the saved locations. An offline saved data folder remains visible so
you can reconnect it or choose another; browsing falls back to an available
folder. Reopening the program does not automatically select an SPL or scan data.
These preferences belong to your Windows account and are stored outside the
application folder, so updating the packaged app retains them.

## Matching and provenance

The real SPL fixture contains distinct original filenames that older normalized
names can collapse together. The parser now retains `source_file_name` as an
additional field; existing normalized columns and PE field mappings are preserved.
Qt matches the original filename case-insensitively. If that exact acquisition is
missing, it remains missing even when a similarly normalized acquisition exists.

Rows with inferred filenames use the existing matcher, followed by an explicitly
disclosed unique dash/underscore alias when needed. Multiple alias candidates
remain unavailable. No similarity-based guessing is used for original filenames.

**Vial** is the instrument's vial position; **List row** is the source database
record position. These are independent and can differ, especially when vials are
reused. Sorting/searching does not change either. The unrelated automatic table
row counter is hidden. Blank or unreadable records are disclosed in the library
context, and surviving records retain their positions instead of being
renumbered. Invalid referenced record boundaries stop the import with an error.

The reader applies a local correction for Jet overflow-record boundaries:
flags on both the start and end offsets are removed before extracting the row.
This prevents adjacent records being combined and then incorrectly discarded.
The installed access-parser dependency and original SPL files are not modified.

Loaded traces retain their SPL list metadata, row fields, original source index
and matching rule. Figure JSON sidecars include these under
`source_metadata.sample_list`, alongside source path, function and signal history.
Acquisitions are read in place. No signal processing was added by this stage;
TIC/PENX behavior remains as described in the [figure guide](QT_PROTOTYPE.md).

## Validation on September 19, 2026

The initial stage-1 checkpoint below is followed by
[loading, axes and navigation refinements](QT_REFINEMENTS.md).
The historical 72-row counts below describe that checkpoint. The September 30
overflow-boundary correction recovers two additional records from this fixture
(`ADTP_CC7` and `ADTP_SM1_2`): 74 readable records out of 75, with one blank record
explicitly disclosed. The earlier 72-source loading measurement does not certify
those additional acquisitions.

- **33 tests passed:** 25 desktop/model/library tests and 8 existing SPL tests.
  New checks cover real-list discovery, input types, original-filename collisions
  and missing runs, alias ambiguity, search/sort selection, refresh/cancel,
  bounded loading, failure/retry, close, deduplication and sidecar provenance.
- **Real acquisitions:** all 72 SPL rows match 72 distinct original filenames
  in the privately supplied folder. All 72 load through the existing adapter:
  68 have 7,916 points and four have 1,200; each has one eligible MS function.
  SHA256 checks found all 739 acquisition files unchanged after verification.
- **Qt workflow:** offscreen discovery and selection opened three real sources
  through the actual child-process queue, preserving identity and SPL details.
  Local library/workspace screenshots were visually inspected. This is automated
  Qt evidence, not manual verification of native dialogs or interaction.
- **Timing scope:** one adapter pass took 11.484 seconds on the development PC.
  This is not a startup or Streamlit comparison benchmark.
- **Packaged build:** rebuilt successfully; the complete folder is 288,521,442
  bytes (about 275 MiB). Startup/PNG/PDF/SVG export, synthetic PENX loading,
  real 72-row SPL discovery, PENX folder discovery, and expected error paths
  passed from an unrelated working directory with Python environment overrides
  removed and PATH limited to Windows. The real SPL is an external test input,
  not bundled private data. No clean-machine claim is made by this host check.

Private acquisitions and screenshots are excluded from source distribution.
Real GC-FID, vendor-reference comparison, native/high-DPI interaction and a
restricted lab PC with no Python installation remain unverified. The bundled
package includes Python; copying only the executable is insufficient.

## Repeat checks

Run from the project root using its isolated Qt environment:

```bat
set QT_QPA_PLATFORM=offscreen
.venv-qt\Scripts\python.exe -m unittest discover -s tests/desktop -v
.venv-qt\Scripts\python.exe -m unittest discover -s tests -v
.venv-qt\Scripts\python.exe -m tools.check_library --folder "D:\Acquisitions" --spl "D:\Lists\run.SPL" --output build\real-library --check-all
.venv-qt\Scripts\python.exe -m PyInstaller --noconfirm qt_prototype.spec
.venv-qt\Scripts\python.exe -m tools.check_package --exe dist\ChromatogramViewer\ChromatogramViewer.exe --output build\package-check
set QT_QPA_PLATFORM=
```

`check_library` is explicitly opt-in to a supplied data path. It hashes inputs,
optionally loads every available source with `--check-all`, and checks up to three
selected sources through Qt (or choose `--load-count`). `--search` narrows the Qt selection. Its local output
contains sample identities and plotted signals: keep it private. Use evidence
folders outside acquisition directories. No data paths are hardcoded in the app.
# Sidebar selection

Opened sample rows use the same neutral selection colors as the library and
analysis tables. Shift-click selects a range; Ctrl-click toggles a sample.
Drag from empty list space to draw a blue selection box. Dragging a sample row
reorders the selected rows instead. **Remove (N)** removes the visible selected
samples from this session and cancels their pending loads; source files are never
deleted. Hidden search results are excluded from removal.

# tcfid: developer notes

tcfid is a PerkinElmer TotalChrom GC-FID reader, integrator and report writer. It was built to be merged into the main Qt application. Version 0.3.1.

Companion documents:
- [README.md](README.md): usage.
- [FORMAT.md](FORMAT.md): file format details and verification evidence.

---

## 1. Why this exists

The teaching lab's Clarus 500 GC-FID runs TotalChrom 6.3.2, and that installation is failing. Data acquisition still works: raw files are complete and valid. Processing does not:

- result files (.rst) from the 2026 runs are empty;
- some files on the PC were deleted.

The goal was to read TotalChrom raw data independently and reproduce TotalChrom's processing, so that integration and reporting can move into the lab's own software. The main app owns the user interface, so this package is deliberately UI-free.

## 2. What was done

1. **Decoded the file format.** TotalChrom files use one container format (`PENX`), read field by field (§5.1). The raw-file layout was worked out against three kinds of TotalChrom output:
   - the ASCII exports (.rax) of three 2026 runs;
   - the result files (.rst) of four 2025 runs;
   - five printed 2025 reports.
2. **Wrote a self-checking reader** (`tcfid/raw.py`). It matches TotalChrom's own export point for point and refuses to return misaligned data.
3. **Recovered the units and time axis exactly:**
   - µV per count comes from the file itself;
   - the time of point *i* is (i + 1)/rate.

   Both reproduce TotalChrom's stored numbers to floating-point precision.
4. **Reproduced TotalChrom's integration** (`tcfid/integrate.py`). The math (baseline, area, height, retention time) is exact. Peak detection follows the TotalChrom manual and matches TotalChrom's results closely (§3).
5. **Added peak identification** from a component table (`tcfid/identify.py`), **plotting** (`tcfid/plotting.py`) and **PDF reports** (`tcfid/report.py`).
6. **Built two test front-ends:**
   - a Qt viewer (`tools/tc_viewer.py`, with its logic in `tools/viewer_core.py`);
   - a command-line tool (`tools/tc_testapp.py`).
7. **Added solvent handling and report layout options (0.3.0).**
   - The solvent peak is detected automatically; an optional automatic solvent delay leaves it out of the peak table.
   - The main plot starts after the solvent, while the full-scale strip keeps it in view.
   - The y-axis reads "Response (mV)", and minor tick marks are added.
   - The report header's fields and labels can be chosen, and all layout options round-trip through JSON.
8. **Aligned the report plots and added a page-break option (0.3.1).** The plots' y-axis labels now start exactly on the text margin, both plots share one left spine, and the right spines sit on the right margin. An option moves the peak table onto the next page.
9. **Wrote 40 unit tests.** 23 always run (synthetic, report, API and viewer-logic tests); the other 17 run when the real test files are available.

## 3. Results at a glance

**Reader**

| Check | Result |
|---|---|
| Point values against TotalChrom's ASCII export (3 runs) | identical |
| Header walk on 8 files, with data starting at bytes 1008 and 1020 | data array found exactly; all self-checks pass |

**Units and time** (checked against 11 peaks in 4 result files)

| Check | Result |
|---|---|
| µV per count = 1/(2 × 54.01791) = 9.2562 nV/count | TotalChrom's areas reproduced to about 1e-15 relative error |
| Point times = (i + 1)/12.5 s | TotalChrom's stored start and end times reproduced exactly |

**Integration against TotalChrom** (2025 runs, TotalChrom's stored settings)

| Check | Result |
|---|---|
| Area, height and retention time, given TotalChrom's boundaries | exact to floating-point precision |
| Peak lists (5 runs) | identical |
| Peak ends (11 peaks) | 11/11 exact |
| Peak starts (11 peaks) | 4/11 exact; the rest 1–2 points early |
| Areas, using our own detection | within 0.011% of TotalChrom, except one 0.3 mV peak (−2.8% area, −1.2% height; no .rst to compare boundaries) |

**Speed** (development machine)

| Step | Time |
|---|---|
| Read one run | 0.2 ms |
| Integrate one run | 5 ms |
| PDF report | about 0.2 s per page |

## 4. Architecture

```
tcfid/                         numpy only unless noted
  penx.py       PenxReader: sequential reads of the container encoding
  raw.py        read_raw() -> RawRun (counts, times, µV, header, checks, sha256)
  integrate.py  IntegrationParams, TimedEvent, integrate() -> IntegrationResult(Peak...),
                find_solvent_peak(), integrate_skipping_solvent()
  identify.py   Component, identify() -> {peak number: name}, missing
  plotting.py   plot_chromatogram(ax, ...), main_view_range()           (matplotlib)
  report.py     write_report(path, entries, options), ReportOptions,
                HEADER_FIELDS, header_items()                            (matplotlib)
  compat.py     parse_penx(), is_penx_file(), find_raw_files()  (old-API drop-in)
tools/          test front-ends (not for the main app)
tests/          unittest suite; reference.py decodes TotalChrom .rst/.rax (tests only)
```

Data flow: `read_raw` → `integrate` → `identify` → `plot_chromatogram` / `write_report`.

**Design rules**
- **No hidden processing.** `RawRun.counts` are the stored integers, and the µV conversion is a documented constant from the file. There is no smoothing, normalization or offset anywhere.
- **The reader checks itself.** Every read verifies the stored point count, the stored min/max and run time × rate. A structural mismatch raises `PenxFormatError`.
- **Settings are explicit.** `IntegrationParams` has no lab-specific defaults. `to_dict()` / `from_dict()` give JSON-safe settings, and components have the same pair.
- **UI-free and side-effect-free.** There are no Qt imports and no pyplot. Reports use matplotlib `Figure` objects inside `rc_context`, so the host app's global rcParams are never changed (a test checks this).
- **matplotlib is optional for the core.** `import tcfid` needs only numpy. Import `tcfid.plotting` and `tcfid.report` explicitly when you need them.

## 5. How it works

### 5.1 Container and raw file

Every TotalChrom file starts with `PENX` and a file-type code (1 = raw data). The encoding:
- big-endian 32-bit integers;
- text stored as a length plus zero-padded bytes;
- doubles stored as two big-endian words, low word first.

There is no offset table, so the header must be walked field by field. Its length varies with the text it contains (paths, sample names), and the data array starts wherever the header ends.

`read_raw`:
1. Walks the file header, data header, A/D header and sequence row.
2. Reads the counted data array.
3. Walks the footer as far as the A/D box and the instrument configuration, where the sampling rate and the µV scale live.

The full field list is in FORMAT.md §2.

- **Units:** `uv_per_count = 1 / (scale × multiplier)`, using channel A's pair from the instrument configuration, (54.01791, 2.0).
- **Time:** `delay + (i + 1) / rate`. The delay has been 0 in every file seen.
- **Clipping:** the A/D ceiling is 107,374,178 counts (993.88 mV). `RawRun.clipped` marks points within 16 counts of it.
- **Provenance:** `RawRun.sha256` is the hash of the file bytes, for provenance records.

### 5.2 Integration (`integrate.py`)

Thresholds use TotalChrom's units:
- NT is compared with the rise between consecutive points, in µV.
- AT is compared with a running sum of point heights, in µV, not an area in µV·s. FORMAT.md §4 has the evidence.

The steps:

1. **Bunching.** Points are averaged in groups of the bunching factor (BF). Each bunch sits at the time of its last raw point.
2. **Start.** A rise greater than NT between consecutive bunches marks a potential start. It is confirmed when the running sum of heights above the start point exceeds AT, while each step keeps rising by more than NT.
3. **Top.** The highest point after the start, confirmed once the drops after it sum to more than ⅔ AT. A higher point restarts that test.
4. **End.** The second of two consecutive steps smaller than NT/2. If a new confirmed rise comes first, the peak is fused with the next one and split at the valley.
5. **True start.** The lowest raw point up to 5 bunches before the potential start, never earlier than the previous peak's end.
6. **Clusters.** Fused peaks share one straight baseline with drop lines at the valleys. A valley whose height is at most `valley_to_peak_ratio` × the smaller peak's height splits the cluster, giving each part its own baseline.
7. **Metrics** (exact against TotalChrom):
   - **baseline:** a straight line from start to end;
   - **area:** the trapezoid sum of (signal − baseline) × Δt;
   - **retention time:** the top of a least-squares parabola through the 5 highest points;
   - **height:** that top value minus the baseline at the retention time;
   - **clipped peaks:** the first point at the maximum is used for time and height.
8. **Flags:**
   - `out-of-range`: the peak reached the A/D ceiling;
   - `baseline-penetration`: the signal dips more than NT/2 below a drawn baseline. TotalChrom adjusts the baseline in this case; this package only flags it.

Timed events: `-P` / `+P` switch detection off and on; `NT` / `AT` change the thresholds from the given time.

**Solvent peak.** `find_solvent_peak(result)` looks for the solvent in two ways:
1. the earliest peak clipped at the A/D limit;
2. if nothing is clipped, the tallest peak, when it is at least 10× taller than every other.

Small artifacts that come before the solvent (seen at NT 5 µV) are ignored.

`integrate_skipping_solvent(run, params)` is the automatic solvent delay. It integrates once to find the solvent, then again with −P at 0 and +P at the solvent's end, keeping any later events. On all 8 runs, at both NT 50 and NT 5 µV, the later peaks come out identical, point for point and area for area. The solvent and anything before it leave the table, so area % then sums over the remaining peaks. That no longer matches TotalChrom's printouts, which included the solvent.

The grey band in the plots is the detection-off window, from a solvent delay or ±P events. It hides no data.

**Choosing NT.** NT sets a minimum slope, and the end rule cuts off tail area in proportion to NT. With the 2025 setting of NT = 50 µV, a 1 mV peak loses about 17% of its area and a 5 mV peak about 2%. At NT = 5 µV, both are within 1% (table in FORMAT.md §4). TotalChrom compatibility and accuracy on small peaks pull in different directions. The lab should choose deliberately and record the choice with the results (use `IntegrationParams.to_dict()`).

### 5.3 Identification (`identify.py`)

Components are taken in order of expected retention time. Each claims the closest still-unnamed peak within ±window (default 0.05 min). Components that aren't found are returned in a list. This mirrors TotalChrom's retention-time windows without its reference-peak or relative-window options.

### 5.4 Plotting and reports

`plot_chromatogram(ax, run, result, names, x_range=..., hide_solvent=..., zoom_to_peaks=..., peak_labels=..., legend=...)` draws onto any Axes:
- the signal, labelled "Response (mV)";
- shaded detection-off windows;
- clipped points;
- baselines and shaded areas;
- peak labels, placed from measured text sizes (named peaks first; any label whose box would overlap another is dropped);
- major and minor tick marks.

`main_view_range(run, result)` starts the view at the later of two times: the solvent's end, or the end of a detection-off window that begins the run. The legend lists only what is visible.

`write_report(path, entries, options)`:
- **One entry:** that run's pages.
- **Several entries:** a summary page first (one row per run, with component areas), then each run.
- **A run page:**
  - a header block whose fields, labels and order come from `ReportOptions.header_fields` (see `HEADER_FIELDS`: sample, study, vial, injected, sequence, file, instrument, method, data, integration, timed events, solvent, components, SHA-256), plus fixed `extra_fields`;
  - a full-scale strip (whole run) and a main view that starts after the solvent and is fitted to the unclipped peaks;
  - the peak table, continued on further pages when long;
  - notes on totals, flags, missing components and warnings.

  The main plot shrinks (to no less than 2.6 in) when that keeps a run on one page. With `peak_table_new_page`, the table starts on the next page and the main plot grows to fill page 1 (up to 6 in).
- **Alignment:** after a page is drawn, `_align_plot_axes()` measures the rendered text. It puts every plot's y-axis label on the left margin, gives all plots one shared left spine just clear of the widest tick labels, and ends every plot on the right margin, so plots line up with the header text, rules and tables.
- **Every page:** a running header, "Page i of N", the generation time, the version and the disclaimer.

Page layout is computed first so that page totals are known before drawing. Fonts are embedded as TrueType (DejaVu Sans, which ships with matplotlib), so text is searchable and µ, · and Δ render correctly. Letter and A4 are both supported; tables scale to the page width.

## 6. The old parser (`instruments/penx_parser.py`)

Measured on the same files.

| Problem | Effect | Fix in tcfid |
|---|---|---|
| Assumed the data start at byte 0x400 (1024) and took the first value > 100,000 | The data actually start at byte 1008 (2026 files) or 1020 (2025 files), so the first 4 or 1 points were dropped. If a header were longer than 1 KB it would start inside header text. | Walk the header; use the stored point count. |
| Found the end by scanning for 20 consecutive "low" values | Read 10,877 / 10,882 points instead of 9,875. About 1,000 footer bytes were plotted as signal (values up to 3.76 × 10⁹), and the trace ran to 14.5 min instead of 13.17. | Counted array, checked against the header. |
| Timed the first point it read as t = 0 | Every retention time was early by 0.40 s (2026) or 0.16 s (2025). | TotalChrom's convention, (i + 1)/rate. |
| "Baseline correction" subtracted the minimum | The footer junk contains zeros, so it subtracted 0 and did nothing. The subtraction isn't meaningful for integration anyway. | No offsets. `compat.parse_penx(..., baseline_offset="min")` keeps the look if plots need it. |
| Returned raw counts with no unit | Areas couldn't be compared with TotalChrom, and thresholds had no physical meaning. | µV from the file's own scale. |
| Read the sampling rate from the `RATE` instrument-parameter text, falling back silently to 12.5 | Correct for these files only by coincidence; wrong without any warning if the text isn't found. | The A/D box's stored rate, with a run time × rate check. |
| Read text at fixed byte offsets, or by searching for marker bytes | Wrong metadata: `operator` was always "TCProcess" (the program that last modified the file); `instrument_serial` was "None" or ""; `autosampler` depended on header length; instrument, description, column, inlet and A/D range were `None`. | Sequential walk with named fields. |
| Read values as unsigned | Negative signals would have become about 4 × 10⁹. | Signed integers (the container's type). |
| Helpers smoothed and normalized by default (`get_fid_trace(sm=5)`, `fid_to_df(norm=True)`) | Hidden processing, against the app's "no implicit smoothing" rule. | Not reproduced; smoothing is a view option if ever wanted. |
| No clipping detection | Integrated the clipped solvent peak with no warning. | `clipped` mask and the `out-of-range` flag. |

## 7. Integrating into the main Qt app

**Files to copy**

| From this package | Suggested place in the app |
|---|---|
| `tcfid/` (whole folder) | The repository root, or under `instruments/`. Imports inside the package are relative, so it can live anywhere. |
| `tests/test_raw.py`, `tests/test_integration.py`, `tests/test_report.py`, `tests/test_api.py`, `tests/reference.py`, `tests/synthetic_run.py` | The app's test folder, keeping `reference.py` test-only. |
| `DEVELOPMENT.md`, `FORMAT.md` | `docs/` |

`tools/` is for reference only. `viewer_core.Session` shows the controller logic to reproduce, and `tc_viewer.py` shows the widget wiring. Don't ship `reference.py` or `tools/` in the app build.

**Replacing the old parser.** There are two options:
- **Fastest:** change imports from `instruments.penx_parser` to `tcfid.compat`. `parse_penx`, `is_penx_file` and `find_raw_files` keep their call shapes, with the fixes above. Values are now in µV and are not offset; pass `baseline_offset="min"` if existing plots rely on a baseline at 0.
- **Target:** use `read_raw(path)` directly: `run.times_min`, `run.microvolts`, `run.header.*`, `run.clipped`, `run.sha256`.

**Wiring the analysis.**
- Integration takes about 5 ms per run, so it can run on the UI thread, re-integrating whenever a setting changes, as the viewer does.
- Run all-runs reports in a worker (at about 0.2 s per page). Rendering matplotlib `Figure` objects off the GUI thread is safe because the report never touches pyplot or the on-screen canvas.
- For baselines and labels, the app's own plotting can either call `plot_chromatogram` on its Axes or draw from `Peak.baseline_counts × run.uv_per_count` and `Peak.rt_min`.

**Saving settings.**
- Store `IntegrationParams.to_dict()` and `[c.to_dict() for c in components]` as JSON with the app's method or sequence data.
- Put the file's `sha256`, `tcfid.__version__` and the settings dictionary in the app's existing provenance sidecars. Reports already print the hash, version and settings.

**Reports.** Save the lab's layout with `ReportOptions.to_dict()` and restore it with `from_dict()`. The viewer's Options dialog shows one way to build the settings UI: `viewer_core.form_from_options()` / `options_from_form()` convert between options and plain form values.

```python
from tcfid.report import ReportEntry, ReportOptions, write_report
info = write_report(path, [ReportEntry(run, result, names, missing), ...],
                    ReportOptions(title="CHEM 0260 GC-FID", subtitle="Nicotine, Monday 1 PM", page_size="letter"))
```

**Packaging.** No new dependencies: numpy 2 (for `np.trapezoid`), matplotlib and PySide6 are already in the app. PyInstaller finds `matplotlib.backends.backend_pdf` through the normal import, and the DejaVu fonts come with matplotlib's data files.

**Test data.** The acquisitions contain lab, computer and student folder names, so keep them outside the repository. Point `TCFID_TEST_DATA` at them; tests that need them skip otherwise, and the skip message says why.

## 8. Tests

```
set TCFID_TEST_DATA=C:\path\to\tc_test_data
python -m unittest discover -s tests -v
```

There are 40 tests. 23 run anywhere (synthetic, report, API and viewer-logic tests); the other 17 need the real files.

| File | Covers |
|---|---|
| `test_raw.py` | point-for-point match with .rax; clean reads of all files; metadata; header-length variation, including a re-written longer text field; corrupt, truncated and wrong-magic files; the clipping ceiling |
| `test_integration.py` | exact math given TotalChrom's boundaries; detection against TotalChrom (peak count, ends, starts within 2 points, area within 0.02%); printed reports; synthetic peaks (accuracy at low NT, truncation at high NT, minimum slope, the detection-off window, fused pairs); solvent detection and the automatic solvent delay (later peaks unchanged; existing events kept) |
| `test_report.py` | one-page and multi-page runs; summary page and component columns; runs with no peaks; letter and A4 widths; no global rcParams changes; header field choice, labels and extras; option validation; JSON round-trip; every option renders; plots aligned to the text margins; peak table on a new page |
| `test_api.py` | JSON round-trips; SHA-256; the drop-in `parse_penx` |
| `test_viewer_core.py` | the viewer's logic: folders, integrate, identify, compare, CSV, reports; the options dialog's form conversion |

## 9. Known limitations and open questions

1. **True peak start.** TotalChrom's exact rule is still unknown (4/11 exact). The effect on areas is ≤ 0.011% here, but larger on tiny peaks.
2. **Untested against TotalChrom** (no reference data yet): fused peaks and valley splitting, bunching factor > 1, NT/AT events, and how the area of a shared valley point is split. The most useful next data would be TotalChrom result files from runs with overlapping peaks.
3. **Not implemented:**
   - the width-ratio criterion (accepted but unused);
   - exponential and tangent skims;
   - negative peaks;
   - split-peak and forced-baseline events;
   - TotalChrom's baseline-penetration adjustment;
   - calibration and quantitation (external or internal standard);
   - reading TotalChrom method (.mth) and sequence (.seq) files.
4. **Unknown field meanings:**
   - the "2" in the unit scale pair; channel B can't be converted yet because its multiplier is 0;
   - the delay term in the time axis (never non-zero so far);
   - the labels of some header fields (FORMAT.md §2).
5. **Not validated.** This is not a validated analytical system (no 21 CFR 11 or GLP). Reports say so in their footer.

## 10. File inventory

| File | Purpose |
|---|---|
| `tcfid/__init__.py`, `_version.py` | public API, version 0.3.1 |
| `tcfid/penx.py` | container reader |
| `tcfid/raw.py` | raw-file reader, `RawRun`, `RawHeader` |
| `tcfid/integrate.py` | TotalChrom-compatible integration |
| `tcfid/identify.py` | component identification |
| `tcfid/plotting.py` | chromatogram drawing |
| `tcfid/report.py` | PDF reports |
| `tcfid/compat.py` | drop-in for the old parser API |
| `tools/tc_viewer.py`, `tools/viewer_core.py` | Qt test viewer and its logic |
| `tools/tc_testapp.py` | command-line test app |
| `tests/*` | test suite and test-only TotalChrom decoders |
| `README.md`, `FORMAT.md`, `DEVELOPMENT.md` | usage, format reference, these notes |
| `environment.yml`, `requirements.txt` | dependencies |

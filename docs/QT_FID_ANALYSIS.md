# GC-FID analysis and reports

Open a TotalChrom PENX `.raw` **file**, select it in Samples, then choose
**View → FID Analysis** (Ctrl+2). The acquisition must be marked complete.
An `.rst` file is not required and is not imported by the app.

## Integrate a sample

1. Set **Noise threshold (µV)** and **Detection threshold AT (µV)**. Defaults are
   50 and 100. AT is TotalChrom's accumulated-rise threshold; it is **not** a
   minimum peak area in µV·s. A bunching factor of 1 uses the original points.
2. Choose the solvent treatment:
   - **Include all** includes every peak meeting the detection settings.
   - **Exclude before a time** turns detection off before the entered time.
   - **Automatic exclusion** finds a clipped or overwhelmingly tall candidate
     and excludes it and earlier peaks. Inspect the reported effective delay;
     this heuristic does not identify a chemical solvent.
3. Optionally add retention-time assignments on **Names**: component, expected
   retention time and tolerance, both in minutes. An unmatched name is listed
   below the table and in the report. These names are assignments, not confirmed
   identities or concentration measurements.
4. Choose **Analysis → Integrate current FID sample**. The single preview plot shows baselines and peak regions.
   The table includes area in µV·s, height
   in µV, retention time, boundaries, area percentage, clipping and other flags.
   Select a row to zoom to that peak. The plot/table divider can be dragged.

**Hide solvent (view only)** and **Fit peaks** change the on-screen view. They do
not change the peak table. Solvent *exclusion* changes which peaks contribute to
the total area and the area-percentage denominator. Neither operation changes
the source file. A no-peak result is reported explicitly.

For advanced methods, expand **Advanced → Timed events**, which accepts `-P` (detection off), `+P` (on), `NT`
(noise threshold) and `AT` (detection threshold). Times are in minutes; NT/AT
need positive µV values, while on/off values stay blank. Events are applied in
time order. Conflicting events at the same time are rejected. Detection events
at or before a manual exclusion time are also rejected; choose Include all for
a completely custom detection schedule. Automatic exclusion records its actual
generated schedule, including replacement of earlier detection events.

## Save methods and create reports

- **Save method** preserves thresholds, bunching, events, solvent treatment and
  component windows in a versioned JSON file. **Load method** applies it to the
  selected sample; press Integrate again. Invalid/unsupported settings are rejected.
- **Analysis → Report layout…** controls Letter/A4, titles, header fields and their order,
  extra fields, overview, main plot limits, labels, table page break and notes.
  Save/load the layout separately under **Analysis → FID report layout**.
- **File → Export → Export peak table** writes the full numerical table to CSV.
- **File → Export → Create PDF report** writes plots, metadata, a paginated peak table and notes.
  The report uses its saved layout, independently of interactive zoom.
  Every page has a generated date/time and page-number footer. Acquired by, Data,
  Integration, Timed events and SHA-256 are hidden by default; enable them in
  Report layout when needed. Explicitly saved layouts keep their chosen fields.
  Notes contain total area and relevant result warnings (such as clipping), actual
  solvent exclusion and your own notes. General limitations remain in the JSON
  metadata and this guide. Previously saved layouts retain their custom footer.
- CSV and PDF exports include a `.json` sidecar with original-file/count hashes,
  reader and analysis revisions, requested/effective settings, component windows,
  results, units, warnings and output hash. Keep this with the exported file.

Calculations always use the retained original counts and calibration. Smoothing,
normalization, cropping, annotations and axis breaks on **Figure** do not affect
analysis. Figure/data exports remain available in **File → Export**; its data CSV contains
the full calibrated trace, whereas the analysis CSV contains integrated peaks.

Methods, drafts and results stay with each open sample for the current session.
They are not a saved project: save reusable methods/layouts and export results
before closing. Changing integration settings clears stale results. Adding an
empty Names row preserves integration; completing a valid rule updates assignments
immediately without recalculating peaks. Incomplete/invalid naming rows retain the
last results but pause export until corrected or removed. Names edited during an
integration are applied when it finishes; names edited during export cancel that
export so an outdated report is not published. Switching samples or
closing cancels an active operation. **Cancel** stops the owned worker without
publishing output. Source changes require reopening the acquisition.

After integrating a representative sample, open **Names → Use detected peaks for
Names…**. Choose unnamed peaks, edit their proposed names and set a retention-time
tolerance (default ±0.05 min). Clipped peaks start unchecked. **Add to Names**
appends rules while preserving existing names and numerical integration. Peak-number
placeholders can be renamed later; **Save method** keeps the rules for other samples.
Already assigned peaks are omitted so repeating the action does not duplicate them.

The peak, Names and Events tables fit their available width without horizontal
scrolling. The peak table shows the main measurements; select a row for start/end
times, baseline, clipping and flags below it. Hover for more precision; the CSV
retains all columns and numerical precision. Selecting a peak zooms the plot;
**Home** restores the overview defined by Hide solvent/Fit peaks. Back/Forward
also work after peak selections and manual zoom.

**Events** are optional changes to peak detection during a run: `-P` turns it off,
`+P` turns it on, `NT` changes the noise threshold, and `AT` changes the detection
threshold. Leave Events empty to use the same settings throughout the acquisition.
An event affects numerical integration, so changing it requires Integrate again.

Idle integration workers are reused after settings edits/sample switches. The
numerical worker loads PDF/plotting dependencies only when exporting, avoiding
repeated renderer startup while maintaining process cancellation and source checks.

Reports run in a separate process. Outputs are staged and checked before
publication, replacement requires confirmation, and ordinary publication failures
roll back the previous pair. The primary output is published last. This is not a
filesystem-wide atomic transaction across two files during power loss; the JSON
output hash allows a mismatched pair to be detected. Save outside acquisition
folders; acquisition inputs cannot be overwritten.

## Validation and limits

The added three-run RAW/RST/PDF reference corpus contains 15 peaks. The detector
finds the same 4, 5 and 6 peaks with the corresponding RST settings, and the RST
values agree with the printed report precision. Areas computed at the vendor's
own boundaries agree to floating-point precision. Automatic areas can differ:
the largest observed relative difference is about **2.779%** for a small peak.
One small peak has a **0.192%** height-fit difference and **0.000412 s** retention
time difference even using the same boundaries. Starts can be two points early;
one clipped solvent endpoint is one point early. These are characterized
differences, not full TotalChrom equivalence.

The original RAW/RAX point-by-point corpus was not supplied for this stage.
Those external checks remain explicitly skipped. Fused peaks, bunching above 1
and NT/AT events still lack broad vendor validation. Skimming, negative-peak
integration, forced baselines, baseline-penetration correction, calibration and
quantitation are not implemented. The reserved width-ratio setting has no engine
effect, so values other than its reserved default are rejected. Inspect clipped
peaks and warnings; their numerical values may be underestimated.

## Batch reports

Open the acquisitions using the sample library or Open GC-FID, then choose
**FID Analysis → Method → Batch PDF report…**. Select the opened samples to
include. Samples follow the left sidebar's order, with highlighted FID samples
preselected. The current sample's method, names and report layout are the starting
settings; use **Load method / Load layout** to choose saved presets instead.
The displayed settings apply to every selected run and are frozen when started.
**Load method** restores integration thresholds, solvent settings, timed events
and peak-naming rules. **Load layout** restores PDF formatting and visible report
fields without changing calculations. Both use presets previously saved by this
app; they do not import vendor methods.

**Create batch PDF…** writes one PDF with a summary followed by per-sample pages,
plus a JSON file recording every source hash, requested/effective settings,
individual results and report hash. Automatic solvent delays are calculated and
reported separately for each acquisition. Figure processing is never applied.
This operation does not replace each sample's interactive analysis settings/results.

Every selected sample must succeed. Failed or changed inputs are listed in the
status column (hover for the full error); no partial PDF is saved. Correct/reopen
or explicitly deselect failures before retrying. **Cancel batch** stops the worker
and publishes nothing. Existing exports remain intact on cancellation/failure;
replacing an export requires confirmation. Unreadable acquisitions must be fixed
in the library before they can be opened and selected for a report.

### Sidebar selection and integration

Drag samples in the left sidebar to reorder them; the insertion line marks the
destination. Shift-click selects a range and Ctrl-click toggles individual samples.
Selected rows can be dragged together. Ordering is for the current session.

Choose **Integrate selected…**, review the samples, then **Integrate selected**.
The active FID sample supplies one method and naming rules for all selected FID
samples, in sidebar order. GC-MS, pending and hidden rows are excluded; the button
shows the eligible count. Each successful result is available by opening that
sample's FID Analysis tab. Existing report layouts stay unchanged. Failed or
cancelled samples keep their previous results; completed samples keep their new
results. This operation exports no files. The batch PDF action remains separate.

Manual boundary editing and vendor-method import are later work.

Developer checks (private inputs remain outside Git):

```bat
set TCFID_TEST_DATA=C:\path\to\reference-files
.venv-qt\Scripts\python.exe -m unittest discover -s tests -v
.venv-qt\Scripts\python.exe -m unittest discover -s tests/desktop -v
.venv-qt\Scripts\python.exe -m tools.check_fid_analysis --source "C:\path\run.raw" --output build\fid-analysis-check
```

The compact controls above the FID plot provide Integrate and PDF report. Peak CSV export and report layout remain in the top menus. They share the menu actions and availability. Home/history/Pan/Zoom sit directly below the plot, followed by acquisition/status information. Advanced opens with Timed events aligned at the top; expanding it reveals the optional event table.

Untick Analysis > FID Analysis (also under View) to return to Figure; results and edits are retained. Integration keeps the displayed time range. Hide solvent is an explicit view option, initially off; Home restores the overview after peak zoom. Optional categories use full-width expandable headers.

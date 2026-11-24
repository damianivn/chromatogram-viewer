# tcfid 0.3.1: TotalChrom GC-FID reader, integrator and reports

tcfid reads PerkinElmer TotalChrom `.raw` files without TotalChrom. It integrates them the way TotalChrom 6.3.2 does, names peaks from a component table, and writes PDF reports.

The core has no UI and needs only numpy; plots and reports use matplotlib. It is built to be merged into the main Qt application; start with [DEVELOPMENT.md](DEVELOPMENT.md). File-format details and evidence are in [FORMAT.md](FORMAT.md).

## Status

- **Reader:** matches TotalChrom's own ASCII export point for point. It checks itself on every read.
- **Units and time:** exact (µV per count comes from the file; point *i* is at (i + 1)/rate).
- **Integration:** on the 2025 runs:
  - the same peak lists as TotalChrom;
  - area, height and retention time are exact given TotalChrom's peak boundaries;
  - with our own detection, areas are within 0.011% of TotalChrom's (one 0.3 mV peak differs by 2.8%).

## Layout

```
tcfid/        penx.py, raw.py, integrate.py, identify.py   (numpy)
              plotting.py, report.py                       (matplotlib)
              compat.py   drop-in for the old parse_penx() API
tools/        tc_viewer.py + viewer_core.py (Qt test viewer), tc_testapp.py (command line)
tests/        unittest suite; reference.py decodes TotalChrom .rst/.rax (tests only)
```

## Set up

```
conda env create -f environment.yml
conda activate tcfid
```

Or use any Python 3.12 with numpy ≥ 2, matplotlib, and PySide6 (PySide6 is only needed for the viewer).

## Use

```python
from tcfid import read_raw, integrate, identify, IntegrationParams, TimedEvent, Component
from tcfid.report import write_report, ReportEntry, ReportOptions

run = read_raw("tdap mon 1pm004.raw")
params = IntegrationParams(noise_threshold_uv=50, area_threshold_uv=100,
                           events=(TimedEvent(0.0, "-P"), TimedEvent(1.931, "+P")))
result = integrate(run, params)
names, missing = identify(result, [Component("nicotine", 5.34, 0.05)])
write_report("run4.pdf", ReportEntry(run, result, names, missing),
             ReportOptions(title="CHEM 0260 GC-FID", subtitle="Nicotine, Monday 1 PM"))
```

Pass several `ReportEntry` objects to get a summary page (one row per run, with component areas) followed by each run's page. Settings, components and report options all round-trip through JSON with `to_dict()` / `from_dict()`.

**Report layout** (`ReportOptions`):
- **Header block.** `header_fields` lists `(key, label)` pairs in display order: pick from `tcfid.report.HEADER_FIELDS` and rename freely. `extra_fields` adds fixed lines such as `("Course", "CHEM 0260")`. `heading` picks the field shown large.
- **Page break.** `peak_table_new_page=True` puts the peak table and notes on the next page and lets the plots use page 1.
- **Chromatogram.** The top strip always shows the whole run. By default the main view starts after the solvent peak (`hide_solvent`), or you can set `main_start_min` / `main_end_min`. Other options: the y-axis is labelled "Response (mV)", minor tick marks, `peak_labels` (name, RT, both or none), and a legend that lists only what is visible.

**Solvent peak.** `find_solvent_peak()` returns the earliest clipped peak, or else a peak at least 10× taller than all others. `integrate_skipping_solvent(run, params)` sets the solvent delay automatically: peak detection stays off until the solvent peak ends. The solvent and anything before it then leave the peak table and area %, and later peaks are unchanged.

**The grey band** in the plots marks where peak detection is off: the solvent delay, or TotalChrom's −P/+P events. It doesn't remove any data.

## Viewer (Qt)

```
python tools\tc_viewer.py [FOLDER]
```

- **Open folder…** lists every .raw file in the folder; click one to plot it.
- **Integrate** draws baselines and fills the peak table. It re-integrates whenever you change a setting, and stays on as you move between runs.
- **Solvent delay** switches peak detection off until the given time. Tick **Auto: after the solvent peak** to set it per run at the end of the solvent. **Hide solvent** starts the plot after the solvent.
- **Identify peaks** uses the Components table (name, RT, ± window).
- **Compare with TotalChrom** overlays TotalChrom's baselines and areas when a non-empty .rst sits next to the run. **Use TotalChrom's settings** copies its settings.
- **PDF report.** **Options…** opens three tabs:
  - **Page:** title, subtitle, page size, heading, peak table on a new page, notes;
  - **Header fields:** tick the fields to show, rename them, reorder them and add extra lines;
  - **Plots:** full-scale strip, solvent hiding, main-view range, y-fit, peak labels, legend, minor ticks and axis labels.

  **This run… / All runs…** writes the PDF. "All runs" integrates and identifies every run with the current settings.
- **Export CSV…** saves the peak table.

## Command line

```
python tools\tc_testapp.py RUN.raw --nt 50 --at 100 --event=-P@0.0 --event=+P@1.931 --report run.pdf
python tools\tc_testapp.py RUN.raw --nt 50 --at 100 --auto-solvent-delay --report run.pdf
python tools\tc_testapp.py RUN.raw --reference RUN.rst            # TotalChrom's settings + comparison
python tools\tc_testapp.py --compare-dir FOLDER                   # every .raw with a same-named .rst
```

## Tests

```
set TCFID_TEST_DATA=C:\path\to\tc_test_data
python -m unittest discover -s tests -v
```

There are 40 tests. 23 run anywhere; 17 need the real acquisitions. If a test skips, the message says why.

**Test data** (sent separately). Keep these outside the repository, because they contain lab, computer and student folder names. Put them all in one folder:

| Files | Source |
|---|---|
| `sample001.raw` – `sample003.raw` and `sample001.RAX` – `sample003.RAX` | 2026 runs with TotalChrom's ASCII exports |
| `tdap mon 1pm001.raw` – `tdap mon 1pm005.raw` and `tdap mon 1pm001.rst` – `tdap mon 1pm004.rst` | 2025 runs with TotalChrom result files |

TotalChrom's names with spaces and versions with underscores both work.

Not a validated analytical system; reports say so in their footer.

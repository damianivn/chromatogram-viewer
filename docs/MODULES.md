# Reusable modules and development boundaries

gcviewer is one Python project and one Qt application. Its scientific modules
can be used without starting or installing the GUI. The maintained tcfid code
is integrated by responsibility; there is no second app or runtime package.

## Where code belongs

- `gcviewer/data_models/`: immutable Trace, RawHeader/RawRun and MSFunction data,
  retaining original counts, timing, calibration and metadata. These are data
  containers, not fitted models or folders for user files.
- `gcviewer/parsers/`: strict TotalChrom RAW/PENX, Waters/TurboMass, and Jet SPL
  readers. Rainbow loads only when an MS acquisition is opened.
- `gcviewer/analysis/`: FID integration, retention-time assignments, TIC/EIC and
  spectra selection, and explicit smoothing/normalization.
- `gcviewer/figures/`: publication figure state/rendering, comparisons, breaks,
  labels and FID previews. Cohesive figure state/rendering stays together in
  `workspace.py`; source Trace data is separate.
- `gcviewer/reports/`: PDF and numeric/spreadsheet writers and protected output
  publication. Users choose their output folders; reports are not saved here.
- `gcviewer/services/`: parser selection, discovery, document/preset state,
  batch requests and headless workers. Existing JSON/NPZ and worker reuse remain.
- `gcviewer/desktop/`: Qt windows/controls and process ownership.
- `gcviewer/cli/`: command-line entry points.
- `tests/`: scientific/reference, desktop/service and SPL regression checks.
- `tools/`: developer smoke checks, run from the checkout as Python modules.

## Independent installation

In a separate environment, install from this checkout:

```console
python -m pip install .
```

The default package requires NumPy and supports TotalChrom parsing/integration.
Optional extras are `ms`, `spl`, `figures`, `reports`, `excel`, `desktop`, `dev`
and `build`. Examples:

```console
python -m pip install ".[reports]"
python -m pip install ".[ms,spl]"
python -m pip install ".[desktop,excel]"
```

`ms` retains the exact patched rainbow revision. `figures` adds Matplotlib and
SciPy for automatic labels; FID reports need Matplotlib without Qt. `excel`
includes pandas, openpyxl and SPL parsing. Existing requirements/lock files and
Windows launchers remain supported. Version 0.1.0 identifies the initial
installable gcviewer distribution; scientific revisions in `revisions.py` are
independent of the application version.

## FID example

```python
from gcviewer.parsers.totalchrom import read_raw
from gcviewer.analysis.totalchrom_fid import IntegrationParams, integrate
from gcviewer.analysis.retention_names import Component, identify

run = read_raw("sample.raw")
result = integrate(run, IntegrationParams(50.0, 100.0))
names, missing = identify(result, [Component("Reference", 5.34, 0.04)])
```

Thresholds and naming windows above are examples, not method recommendations.
Access original integers as `run.counts`; calibrated values/times are
`run.microvolts`, `run.times_s` and `run.times_min`.

```python
from gcviewer.reports.fid_pdf import ReportEntry, ReportOptions, write_report

write_report("report.pdf", ReportEntry(run, result, names, missing), ReportOptions())
```

The low-level writer writes the requested file directly. Application-level
source/overwrite protection and provenance publication belong to
`services/fid_workflow.py` and `reports/publication.py`.

## MS example

```python
from gcviewer.parsers.waters import load_raw
from gcviewer.analysis.mass_spectra import ms_functions, tic, eic, spectrum

functions = ms_functions(load_raw("sample.raw"), "sample.raw")
function = functions[0]  # select the appropriate recorded MS function
total = tic(function)
ion = eic(function, 91.0)
scan = spectrum(function, 2.5)
mean = spectrum(function, 2.5, 2.8)
```

Selection functions take a data container explicitly. Nearest-channel/scan and
inclusive averaging retain their existing semantics. The data model no longer
performs calculations or imports a reader.

## Entry points and compatibility

- GUI: `python -m gcviewer.desktop`; installed command: `gcviewer`.
- SPL: `python export_spl.py input.SPL -o output.xlsx` remains supported, along
  with `python -m gcviewer.cli.export_spl` and `gcviewer-export-spl`.
- Worker modules: `gcviewer.services.worker` and `gcviewer.services.library`.
  Frozen executable dispatch flags are unchanged.
- Old `desktop`, `shared`, `instruments` and `tcfid` imports are retired; there
  are no forwarding trees or duplicate runtime implementations. The unused
  tuple-return `parse_penx` helper is retired; use the explicit reader above.
- Saved method/layout JSON, worker formats and sidecar fields retain their
  meanings. Historical `tcfid` provenance strings remain because moving files
  does not change the scientific algorithm. Supplied reference notes remain in
  `docs/tcfid/`; original supplied source remains in the private work folder.

## Dependency rules and checks

Models import only models/basic numerical dependencies. Parsers may import
models but do not integrate or plot. Analysis consumes data and explicit
parameters; it never imports parsers, services, reports or Qt. Figures/reports
consume completed data/results without Qt. Services coordinate workflows;
desktop and CLI call these layers. No lower layer reads widget settings.
Ordinary function calls pass the same arrays directly; folder boundaries do
not introduce processes, serialization or extra copies.

Keep initializers light and optional imports lazy. Add instrument decoding to
parsers, detector-specific data to data_models, and calculations to analysis
before exposing them in the UI. Use another package/repository only when a real
distribution need emerges.

```console
python -m unittest tests.test_module_boundaries
python -m unittest discover -s tests -t .
```

Set `QT_QPA_PLATFORM=offscreen` for headless Qt checks. Set `TCFID_TEST_DATA` to
the private reference folder for vendor comparisons; missing files produce
explicit skips. Boundary tests reject reverse imports and exercise FID parsing
and integration with GUI/rendering and other optional packages blocked.

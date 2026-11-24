# Loading, axes and sample navigation

These changes address feedback on the first Qt sample-library build.

## Loading and selection

The app keeps one background parser process ready between acquisitions. Previously
each file started a new process and imported its dependencies again. One acquisition
is still parsed at a time to bound memory use. The worker does not retain raw
acquisition matrices as a cache.

Click a waiting sample to move it **next**. The current parse finishes, then the
selected sample loads ahead of the remaining queue. Rows show Loading, Next,
Queued, Ready or Failed separately from the filename. **Remove** cancels a waiting
or active request. An active cancellation stops the worker; the next request
starts a fresh one. **Retry** is enabled for failed samples. Closing the window
stops the worker, including when it is idle. Already loaded samples and report
edits remain available throughout the session.

## Baseline and intensity labels

Automatic y limits now start at **zero** when every signal value is nonnegative.
Padding remains above the highest peak. Negative values remain visible, and an
explicit **Signal min, max** range still takes precedence. No source signal is
shifted, clipped, normalized or rescaled by these display changes.

The default **Axis numbers → Readable units** labels large signals in thousands,
millions, billions or trillions and states the scale in the y-axis title. For
example, a tick of **2** on an axis labeled **counts — billions** means
2,000,000,000 counts. This replaces the detached `1e10` multiplier, which meant
that `0.2` represented `0.2 × 10¹⁰`, or 2 billion.

Choose **Scientific notation** for a mathematical multiplier or **Full numbers**
for unscaled numeric tick labels, then **Apply to figure**. The setting is stored
per sample. Home returns to automatic ranges while keeping the number style.
Figure exports use the same renderer as the preview; JSON sidecars record the
readable-unit divisor and axis title (scientific mode records an automatic divisor),
while source values and annotation anchors retain
their original units.

## Sample panel

The left panel uses compact single-line rows with the filename and inline load
status. Vial/description, full paths and function names remain available on hover.
At the default font, rows are 24 pixels high; a 1280 × 820 test window showed 24
complete rows. **Find an opened sample…** filters the panel without discarding
samples or their edits. **Add…** opens the sample library; **Remove** and **Retry**
are compact actions. **Sample details** expands acquisition metadata. The workspace
starts empty; the former demo button has been removed.
Drag the divider to change the panel width. Figure dimensions now have presets
including a wide 3:1 format and live custom sizing; see
[figure dimensions](QT_PROTOTYPE.md#figure-dimensions).

## Verification

- 32 desktop/model/Qt checks plus all 8 existing SPL tests pass. New tests cover
  zero/negative/manual axes, readable units/export metadata, selection priority,
  search and retained edits, worker reuse after errors, crash recovery and cancellation.
- All 72 distinct real SPL acquisitions passed through the actual Qt reusable
  worker with correct identity and provenance. All 739 source-file hashes were
  unchanged. Private acquisitions remain outside the repository.
- Offscreen screenshots show the revised sample panel, zero baseline and explicit
  billions axis. PNG/PDF/SVG exports were rendered for independent visual review.
  Native manual/high-DPI and clean lab-PC testing remain separate checks.

### Loading measurements

The previous package took 9.6593 seconds for the first four real SPL acquisitions,
starting a fresh worker each time (2.37–2.48 seconds per file). In the new package,
requests after the first took 0.21–0.27 seconds in the same worker. Trace NPZ files
were byte-identical to the previous package in both comparison runs.

The first launch immediately after rebuilding took 10.4364 seconds for its first
request and 11.0829 seconds for all four. A repeat run took 1.3357 seconds for the
first request and 2.0894 seconds total. Initial startup varied substantially;
these checks do not isolate OS caching or background scanning effects. Therefore
the reliable finding is removal of repeated startup between bulk requests, not
an unconditional first-file speed claim. These single-host measurements include
parsing and result transfer, exclude UI rendering, and are not a controlled
cold-PC or Streamlit comparison.

Reproduce real-data checks using the commands in the
[sample-library guide](QT_SAMPLE_LIBRARY.md), adding `--load-count 72` to exercise
the complete queue. Run the packaged worker comparison with
`python -m tools.check_load_service --exe <exe> --folder <parent> --spl <list> --output <json>`.
The package check also covers a successful request, an error and another successful
request in the same process. Use fresh local output folders.

# Local tcfid adoption

The owner supplied tcfid 0.3.1 as a source folder. Its maintained code is now fully
integrated into gcviewer parsers, data models, analysis, figures and reports;
see [the module guide](../MODULES.md). There is no separate tcfid runtime package.
The companion README, DEVELOPMENT and FORMAT
files in this directory are **the supplied reference notes**, including original
layout/commands and reported results. Current gcviewer usage is documented in
[QT_FID_READER.md](../QT_FID_READER.md).

Reader revision in acquisition metadata: **tcfid-0.3.1-gcviewer-1**. The upstream
package version remains 0.3.1; this revision distinguishes local changes:

- Reject fewer than two points and nonfinite/negative runtime or delay.
- Validate finite positive channel-scale factors/product/conversion.
- Disclose a non-complete acquisition flag as a warning for viewing.

The FID Analysis view now uses integration, identification, plotting and reporting
through an independent app-owned document and worker. Analysis revision
`gcviewer-fid-analysis-1` adds finite/integer/event/component/preset validation,
rejects non-default unused width-ratio values, validates report options and wraps
long report notes. The numerical integration/identification algorithms and original
clipping/unit/time calculations are retained. One original API round-trip test
now uses the supported reserved width default; new tests explicitly reject other
values. Output protection and complete metadata are in the app adapter.

The supplied three-run corpus extends the evidence: automatic boundaries and one
small-peak height fit differ slightly from vendor results. See
[current scope and measurements](../QT_FID_ANALYSIS.md); the original notes remain
a historical reference, not a claim that all new reference values match exactly.

Core/reference tests were copied to `tests/fid_core/`, with namespaced fixture
imports. The test viewer/controller was not imported as runtime code. Its viewer
tests remain with the supplied reference snapshot. A new independent synthetic
PENX writer in `tests/penx_fixture.py` replaces the app's old guessed-layout bytes.
No real acquisition, student data or test-only vendor result decoder is bundled
in the executable. External vendor checks skip with explicit reasons when their
corpus is absent; they are not silently replaced by generated data.

The retired `instruments.penx_parser` wrapper has been removed. Production uses
`gcviewer.parsers.totalchrom.read_raw()` directly. Header detection is in
`gcviewer.parsers.totalchrom.discovery`. The unused legacy tuple-return reader
was retired after application callers migrated to the explicit data model.

No standalone package/repository publication is part of this adoption.

"""PDF report tests (synthetic runs; no data files needed)."""
import re
import tempfile
import unittest
from pathlib import Path

import matplotlib
from pypdf import PdfReader

from tests.fid_core.synthetic_run import gaussian_counts, synthetic_run
from gcviewer.analysis.retention_names import Component, identify
from gcviewer.analysis.totalchrom_fid import IntegrationParams, integrate
from gcviewer.reports.fid_pdf import PEAK_COLS, ReportEntry, ReportOptions, _paginate, _run_section, _summary_section, write_report

PARAMS = IntegrationParams(noise_threshold_uv=50.0, area_threshold_uv=100.0)


def pdf_pages(path: Path) -> int:
    return len(re.findall(rb"/Type\s*/Page(?![s\w])", path.read_bytes()))


def entry(peaks, name="run", components=()):
    run = synthetic_run(gaussian_counts(peaks), name=name)
    res = integrate(run, PARAMS)
    names, missing = identify(res, components) if components else ({}, [])
    return ReportEntry(run, res, names, tuple(missing))


class TestReport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_single_run_is_one_page(self):
        e = entry([(150.0, 2e6, 0.9), (250.0, 1e6, 0.9)])
        info = write_report(self.dir / "one.pdf", e)
        self.assertEqual(info.pages, 1)
        self.assertEqual(pdf_pages(info.path), 1)
        self.assertTrue(info.path.read_bytes().startswith(b"%PDF"))

    def test_long_peak_table_continues_on_new_pages(self):
        peaks = [(60.0 + 13.0 * i, 1e6, 0.9) for i in range(40)]
        e = entry(peaks)
        self.assertEqual(len(e.result.peaks), 40)
        size = (8.5, 11.0)
        pages = _paginate([_run_section(e, ReportOptions(), size)], size)
        rows = sum(len(op[2][1]) for p in pages for op in p["ops"] if op[0] == "table")
        self.assertEqual(rows, 40)
        self.assertGreaterEqual(len(pages), 2)
        info = write_report(self.dir / "long.pdf", e)
        self.assertEqual(pdf_pages(info.path), info.pages)
        generated = []
        for number, page in enumerate(PdfReader(info.path).pages, 1):
            text = page.extract_text()
            self.assertIn(f"Page {number} of {info.pages}", text)
            generated.append(re.search(r"Generated \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", text).group(0))
        self.assertEqual(len(set(generated)), 1)

    def test_several_runs_get_a_summary_page(self):
        comps = [Component("first", 2.5), Component("second", 4.167), Component("never", 9.0)]
        es = [entry([(150.0, 2e6, 0.9), (250.0, (i + 1) * 4e5, 0.9)], f"std{i}", comps)
              for i in range(3)]
        info = write_report(self.dir / "batch.pdf", es, ReportOptions(title="Batch", page_size="a4"))
        self.assertEqual(info.pages, 4)
        for size in ((8.5, 11.0), (8.27, 11.69)):
            _ctx, items = _summary_section(es, size)
            tables = items[1:]
            headers = [c.header for t in tables for c in t.cols[5:]]
            self.assertEqual(headers, ["first", "second", "never"])
            for t in tables:
                self.assertLessEqual(sum(c.width for c in t.cols), size[0] - 1.2 + 1e-9)
            second = next(t for t in tables if "second" in [c.header for c in t.cols])
            col = [c.header for c in second.cols].index("second")
            self.assertEqual(second.rows[2][col], es[2].result.peaks[1].area_uv_s)
            never = next(t for t in tables if "never" in [c.header for c in t.cols])
            self.assertIsNone(never.rows[0][[c.header for c in never.cols].index("never")])

    def test_run_without_peaks(self):
        info = write_report(self.dir / "flat.pdf", entry([]))
        self.assertEqual(info.pages, 1)

    def test_options_and_isolation(self):
        before = dict(matplotlib.rcParams)
        write_report(self.dir / "x.pdf", entry([(150.0, 2e6, 0.9)]),
                     ReportOptions(full_scale_strip=False, zoom_to_peaks=False, notes=("note",)))
        self.assertEqual(dict(matplotlib.rcParams), before)
        with self.assertRaises(ValueError):
            write_report(self.dir / "y.pdf", entry([]), ReportOptions(page_size="legal"))
        with self.assertRaises(ValueError):
            write_report(self.dir / "z.pdf", [])

    def test_peak_table_fits_both_page_sizes(self):
        for size in ((8.5, 11.0), (8.27, 11.69)):
            _ctx, items = _run_section(entry([(150.0, 2e6, 0.9)]), ReportOptions(), size)
            table = next(i for i in items if hasattr(i, "cols"))
            self.assertAlmostEqual(sum(c.width for c in table.cols), size[0] - 1.2)
        self.assertEqual(len(PEAK_COLS), 8)


if __name__ == "__main__":
    unittest.main()


class TestReportOptions(unittest.TestCase):
    def test_header_fields_choice_labels_and_extras(self):
        from gcviewer.reports.fid_pdf import header_items
        e = entry([(150.0, 2e6, 0.9)], name="std 1")
        opts = ReportOptions(header_fields=(("sample", "Standard"), ("vial", "Position")),
                             extra_fields=(("Course", "CHEM 0260"),))
        self.assertEqual(header_items(e, opts), [("Standard", "std 1"), ("Position", "1"),
                                                  ("Course", "CHEM 0260")])
        self.assertEqual(len(header_items(e, ReportOptions())), 9)
        with self.assertRaises(ValueError):
            ReportOptions(header_fields=(("nonsense", "x"),))
        with self.assertRaises(ValueError):
            ReportOptions(peak_labels="fancy")

    def test_json_round_trip(self):
        import json
        o = ReportOptions(title="T", header_fields=(("file", "Data file"),), extra_fields=(("a", "b"),),
                          main_start_min=3.0, peak_labels="rt", notes=("n1", "n2"), page_size="a4")
        self.assertEqual(ReportOptions.from_dict(json.loads(json.dumps(o.to_dict()))), o)

    def test_every_option_renders(self):
        with tempfile.TemporaryDirectory() as tmp:
            e = entry([(150.0, 2e6, 0.9), (250.0, 1e6, 0.9)])
            for opts in (ReportOptions(heading="", heading_time=False, header_fields=()),
                         ReportOptions(heading="file", peak_labels="name_and_rt", legend=False,
                                       minor_ticks=False, y_label="Signal", x_label="t"),
                         ReportOptions(hide_solvent=False, zoom_to_peaks=False),
                         ReportOptions(main_start_min=2.0, main_end_min=6.0)):
                info = write_report(Path(tmp) / "o.pdf", e, opts)
                self.assertEqual(pdf_pages(info.path), info.pages)


class TestLayout(unittest.TestCase):
    def test_plots_line_up_with_the_text_margins(self):
        from gcviewer.reports.fid_pdf import MARGIN_X, _align_plot_axes, _Page, _plot_block
        e = entry([(150.0, 2e6, 0.9), (250.0, 1e6, 0.9)])
        for size, opts in (((8.5, 11.0), ReportOptions()),
                           ((8.27, 11.69), ReportOptions(y_label="A much longer label (mV)"))):
            page = _Page(size)
            usable = size[0] - 2 * MARGIN_X
            _plot_block(e, usable, 1.25, opts, strip=True).draw(page, 2.0)
            _plot_block(e, usable, 3.3, opts, strip=False).draw(page, 3.4)
            _align_plot_axes(page)
            r = page.fig.canvas.get_renderer()
            dpi = page.fig.dpi
            strip, main = page.plot_axes
            for ax in (strip, main):
                self.assertAlmostEqual(ax.yaxis.label.get_window_extent(r).x0 / dpi, MARGIN_X, delta=0.02)
                self.assertAlmostEqual(ax.get_position().x1, 1 - MARGIN_X / size[0], places=9)
                ticks = min(t.get_window_extent(r).x0 for t in ax.get_yticklabels() if t.get_text())
                self.assertGreater(ticks, ax.yaxis.label.get_window_extent(r).x1)
            self.assertAlmostEqual(strip.get_position().x0, main.get_position().x0, places=9)

    def test_peak_table_on_a_new_page(self):
        e = entry([(150.0, 2e6, 0.9), (250.0, 1e6, 0.9)])
        with tempfile.TemporaryDirectory() as tmp:
            one = write_report(Path(tmp) / "a.pdf", e)
            two = write_report(Path(tmp) / "b.pdf", e, ReportOptions(peak_table_new_page=True))
            self.assertEqual((one.pages, two.pages), (1, 2))
            size = (8.5, 11.0)
            pages = _paginate([_run_section(e, ReportOptions(peak_table_new_page=True), size)], size)
            self.assertEqual([op[0] for op in pages[0]["ops"]], ["fixed", "fixed", "fixed"])
            self.assertEqual(pages[1]["ops"][0][0], "table")

"""Integration tests: TotalChrom result files and reports, plus synthetic data (always run)."""
import unittest

import numpy as np

from tests.fid_core.reference import REPORT_TABLES, TDAP_2025_PARAMS, need_file, read_rst
from gcviewer.analysis.totalchrom_fid import IntegrationParams, TimedEvent, integrate, integrate_counts, peak_metrics
from gcviewer.parsers.totalchrom.raw import read_raw

WITH_RST = tuple(f"tdap_mon_1pm00{i}" for i in range(1, 5))


def need(name):
    return need_file(name)


class TestMathMatchesTotalChrom(unittest.TestCase):
    """Given TotalChrom's own peak boundaries, area/height/RT must match exactly."""

    def test_exact_with_totalchrom_boundaries(self):
        for stem in WITH_RST:
            run = read_raw(need(stem + ".raw"))
            ref = read_rst(need(stem + ".rst"))
            t, y = run.times_s, run.counts
            for q in ref.peaks:
                with self.subTest(stem=stem, rt=round(q.rt_s / 60, 3)):
                    t0, t1 = t[q.start], t[q.end]
                    b0 = q.baseline_intercept_counts + q.baseline_slope_counts_per_s * t0
                    b1 = q.baseline_intercept_counts + q.baseline_slope_counts_per_s * t1
                    _apex, rt, h, area = peak_metrics(y, t, q.start, q.end, t0, b0, t1, b1)
                    self.assertAlmostEqual(area * run.uv_per_count / q.area_uv_s, 1.0, delta=1e-9)
                    self.assertAlmostEqual(h * run.uv_per_count / q.height_uv, 1.0, delta=1e-9)
                    self.assertAlmostEqual(rt, q.rt_s, delta=1e-6)


class TestDetectionMatchesTotalChrom(unittest.TestCase):
    def test_same_peaks_and_boundaries(self):
        for stem in WITH_RST:
            run = read_raw(need(stem + ".raw"))
            ref = read_rst(need(stem + ".rst"))
            res = integrate(run, ref.params())
            self.assertEqual(len(res.peaks), len(ref.peaks), stem)
            for p, q in zip(res.peaks, ref.peaks):
                with self.subTest(stem=stem, rt=round(q.rt_s / 60, 3)):
                    self.assertEqual(p.end, q.end)
                    self.assertIn(q.start - p.start, (0, 1, 2))
                    self.assertAlmostEqual(p.rt_min, q.rt_s / 60, delta=5e-4)
                    self.assertAlmostEqual(p.area_uv_s / q.area_uv_s, 1.0, delta=2e-4)
                    self.assertAlmostEqual(p.height_uv / q.height_uv, 1.0, delta=1e-4)
                    self.assertEqual(p.baseline_code, "BB")

    def test_printed_reports(self):
        for stem, table in REPORT_TABLES.items():
            run = read_raw(need(stem + ".raw"))
            res = integrate(run, TDAP_2025_PARAMS)
            self.assertEqual(len(res.peaks), len(table), stem)
            for p, (rt, area, height) in zip(res.peaks, table):
                with self.subTest(stem=stem, rt=rt):
                    self.assertAlmostEqual(p.rt_min, rt, delta=6e-4)
                    small = area < 1000.0
                    self.assertAlmostEqual(p.area_uv_s / area, 1.0, delta=0.05 if small else 2e-4)
                    self.assertAlmostEqual(p.height_uv / height, 1.0, delta=0.02 if small else 1e-4)

    def test_solvent_flagged_out_of_range(self):
        res = integrate(read_raw(need("tdap_mon_1pm001.raw")), TDAP_2025_PARAMS)
        self.assertIn("out-of-range", res.peaks[0].flags)
        self.assertFalse(any(p.clipped for p in res.peaks[1:]))


def synthetic(peaks, n=6000, rate=12.5, noise_counts=55.0, seed=0, baseline=537_000.0):
    """Counts with Gaussian peaks: peaks = [(rt_s, height_counts, sigma_s), ...]."""
    rng = np.random.default_rng(seed)
    t = (np.arange(n) + 1) / rate
    y = baseline + rng.normal(0.0, noise_counts, n)
    for rt, h, sd in peaks:
        y += h * np.exp(-0.5 * ((t - rt) / sd) ** 2)
    return np.round(y).astype(np.int32)


UV = 1.0 / (2.0 * 54.01791)
PARAMS = IntegrationParams(noise_threshold_uv=50.0, area_threshold_uv=100.0)


class TestSynthetic(unittest.TestCase):
    def test_isolated_gaussians_low_threshold(self):
        spec = [(120.0, 3e6, 0.9), (200.0, 5e5, 1.1), (300.0, 2.5e5, 1.0)]
        low = IntegrationParams(noise_threshold_uv=5.0, area_threshold_uv=100.0)
        res = integrate_counts(synthetic(spec), 12.5, UV, low)
        self.assertEqual(len(res.peaks), 3)
        for p, (rt, h, sd) in zip(res.peaks, spec):
            true_area = h * sd * np.sqrt(2 * np.pi) * UV
            self.assertAlmostEqual(p.rt_min * 60, rt, delta=0.02)
            self.assertAlmostEqual(p.height_uv / (h * UV), 1.0, delta=0.01)
            self.assertAlmostEqual(p.area_uv_s / true_area, 1.0, delta=0.01)
            self.assertEqual(p.baseline_code, "BB")

    def test_high_threshold_truncates_small_peaks(self):
        ratios = []
        for h_mV in (2.0, 5.0, 30.0):
            h = h_mV * 1000 / UV
            p, = integrate_counts(synthetic([(200.0, h, 0.7)]), 12.5, UV, PARAMS).peaks
            ratios.append(p.area_uv_s / (h * 0.7 * np.sqrt(2 * np.pi) * UV))
        self.assertLess(ratios[0], ratios[1])
        self.assertLess(ratios[1], ratios[2])
        self.assertGreater(ratios[0], 0.90)
        self.assertGreater(ratios[2], 0.995)

    def test_noise_threshold_sets_a_minimum_slope(self):
        spec = [(200.0, 1.2e5, 1.2)]
        self.assertEqual(integrate_counts(synthetic(spec), 12.5, UV, PARAMS).peaks, ())
        lower = IntegrationParams(noise_threshold_uv=20.0, area_threshold_uv=100.0)
        self.assertEqual(len(integrate_counts(synthetic(spec), 12.5, UV, lower).peaks), 1)

    def test_peak_detection_off_window(self):
        spec = [(60.0, 2e6, 1.0), (200.0, 2e6, 1.0)]
        events = (TimedEvent(0.5, "-P"), TimedEvent(1.5, "+P"))
        res = integrate_counts(synthetic(spec), 12.5, UV,
                               IntegrationParams(50.0, 100.0, events=events))
        self.assertEqual([round(p.rt_min * 60) for p in res.peaks], [200])

    def test_fused_pair_is_split_at_the_valley(self):
        spec = [(150.0, 2e6, 1.0), (154.0, 1.2e6, 1.0)]
        res = integrate_counts(synthetic(spec), 12.5, UV, PARAMS)
        self.assertEqual([p.baseline_code for p in res.peaks], ["BV", "VB"])
        self.assertEqual(res.peaks[0].end, res.peaks[1].start)
        total = sum(h * sd * np.sqrt(2 * np.pi) for _, h, sd in spec) * UV
        self.assertAlmostEqual(res.total_area_uv_s / total, 1.0, delta=0.03)


if __name__ == "__main__":
    unittest.main()


class TestSolvent(unittest.TestCase):
    def test_solvent_is_the_first_clipped_peak(self):
        from gcviewer.analysis.totalchrom_fid import find_solvent_peak
        run = read_raw(need("tdap_mon_1pm005.raw"))
        low = integrate(run, IntegrationParams(5.0, 100.0))
        sol = find_solvent_peak(low)
        self.assertTrue(sol.clipped)
        self.assertAlmostEqual(sol.rt_min, 2.328, delta=0.002)

    def test_auto_solvent_delay_keeps_later_peaks(self):
        from gcviewer.analysis.totalchrom_fid import find_solvent_peak, integrate_skipping_solvent
        for stem in REPORT_TABLES:
            run = read_raw(need(stem + ".raw"))
            for nt in (50.0, 5.0):
                full = integrate(run, IntegrationParams(nt, 100.0))
                sol = find_solvent_peak(full)
                skipped, delay = integrate_skipping_solvent(run, IntegrationParams(nt, 100.0))
                self.assertAlmostEqual(delay, sol.end_min)
                later = [(p.start, p.end, p.area_uv_s) for p in full.peaks if p.start >= sol.end]
                self.assertEqual([(p.start, p.end, p.area_uv_s) for p in skipped.peaks], later)
                self.assertAlmostEqual(sum(p.area_pct for p in skipped.peaks), 100.0)

    def test_synthetic_solvent_rules(self):
        from gcviewer.analysis.totalchrom_fid import find_solvent_peak, integrate_skipping_solvent
        tall = integrate_counts(synthetic([(100.0, 5e7, 1.0), (300.0, 1e6, 1.0)]), 12.5, UV, PARAMS)
        self.assertEqual(find_solvent_peak(tall).number, 1)
        even = integrate_counts(synthetic([(100.0, 2e6, 1.0), (300.0, 1e6, 1.0)]), 12.5, UV, PARAMS)
        self.assertIsNone(find_solvent_peak(even))
        y = synthetic([(100.0, 5e7, 1.0), (300.0, 1e6, 1.0), (400.0, 1e6, 1.0)])
        from tests.fid_core.synthetic_run import synthetic_run
        run = synthetic_run(y)
        keep = IntegrationParams(50.0, 100.0, events=(TimedEvent(6.5, "-P"), TimedEvent(7.0, "+P")))
        res, delay = integrate_skipping_solvent(run, keep)
        self.assertEqual([round(p.rt_min * 60) for p in res.peaks], [300])
        self.assertEqual([e.kind for e in res.params.events], ["-P", "+P", "-P", "+P"])

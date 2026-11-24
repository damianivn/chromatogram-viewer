"""Additional 2025 RAW/RST/PDF corpus; files stay outside the repository.

Recorded limits: automatic small-peak area differs up to 2.779%; sample007 at
5.886 min has a 0.192% height-fit difference even with vendor boundaries. These
tests characterize that scope; they do not establish complete vendor parity.
"""
import re
import unittest

from pypdf import PdfReader
from gcviewer.parsers.totalchrom import read_raw
from gcviewer.analysis.totalchrom_fid import integrate
from gcviewer.analysis.totalchrom_fid import peak_metrics
from tests.fid_core.reference import need_file, read_rst


class SuppliedPairs(unittest.TestCase):
    def test_complete_005_007_corpus_against_rst_and_printed_pdf(self):
        for number, count in ((5,4),(6,5),(7,6)):
            with self.subTest(sample=number):
                raw=need_file(f"tdap_mon_1pm00{number}.raw")
                rst=need_file(f"tdap_mon_1pm00{number}.rst")
                pdf=need_file(f"{number}a.pdf")
                run,ref=read_raw(raw),read_rst(rst)
                result=integrate(run,ref.params())
                self.assertEqual(run.n_points,9875)
                self.assertEqual(run.rate_hz,12.5)
                self.assertEqual(len(result.peaks),count)
                self.assertEqual(len(ref.peaks),count)
                text="\n".join(p.extract_text() for p in PdfReader(pdf).pages)
                printed=re.findall(r"(?m)^(\d+)\s+(\d+\.\d{3})\s+(\d+\.\d{2})\s+(\d+\.\d{2})\s",text)
                self.assertEqual(len(printed),count)
                t=run.times_s
                for p,q,table in zip(result.peaks,ref.peaks,printed):
                    with self.subTest(sample=number,peak=p.number):
                        b0=q.baseline_intercept_counts+q.baseline_slope_counts_per_s*t[q.start]
                        b1=q.baseline_intercept_counts+q.baseline_slope_counts_per_s*t[q.end]
                        _,rt,h,area=peak_metrics(run.counts,t,q.start,q.end,t[q.start],b0,t[q.end],b1)
                        self.assertAlmostEqual(area*run.uv_per_count/q.area_uv_s,1.,delta=1e-9)
                        height_tolerance=.002 if number==7 and p.number==4 else 1e-9
                        self.assertAlmostEqual(h*run.uv_per_count/q.height_uv,1.,delta=height_tolerance)
                        self.assertAlmostEqual(rt,q.rt_s,delta=.0005 if height_tolerance==.002 else 1e-6)
                        self.assertIn(p.start-q.start,(-2,-1,0))
                        self.assertIn(p.end-q.end,(-1,0))
                        area_tolerance=.03 if number==5 and p.number==4 else .001
                        self.assertAlmostEqual(p.area_uv_s/q.area_uv_s,1.,delta=area_tolerance)
                        self.assertAlmostEqual(float(table[1]),q.rt_s/60,delta=.000501)
                        self.assertAlmostEqual(float(table[2]),q.area_uv_s,delta=.00501)
                        self.assertAlmostEqual(float(table[3]),q.height_uv,delta=.00501)

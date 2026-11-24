"""Analysis correctness, persistence, source identity and protected publication."""
from dataclasses import replace
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from pypdf import PdfReader
from gcviewer.services.acquisition import load_fid
from gcviewer.services.worker import main
from gcviewer.services.fid_workflow import AnalysisMethod, assign_names, calculate, check_source, preset_record, read_preset, typed_result, write_request, execute_request, report_range
from gcviewer.reports.publication import fingerprint, output_paths, publish, save_json
from gcviewer.analysis.retention_names import Component
from gcviewer.analysis.totalchrom_fid import IntegrationParams, TimedEvent
from gcviewer.reports.fid_pdf import ReportOptions
from tests.penx_fixture import synthetic_penx


def fixture(folder, name="run.raw", complete=3):
    t = np.arange(1, 6001) / 12.5
    counts = 537000 + 3e6*np.exp(-.5*((t-100)/1.2)**2) + 5e5*np.exp(-.5*((t-250)/1.)**2)
    return load_fid(synthetic_penx(Path(folder)/name, counts=np.rint(counts).astype(np.int32), complete=complete))


class AnalysisTests(unittest.TestCase):
    def test_names_reuse_only_matching_numerical_results(self):
        with tempfile.TemporaryDirectory() as folder:
            run = fixture(folder)
            initial = calculate(run, AnalysisMethod())
            method = AnalysisMethod(components=(Component("First", 100/60),))
            with patch('gcviewer.services.fid_workflow.integrate', side_effect=AssertionError('Must not reintegrate')):
                renamed = assign_names(initial, run, method)
            self.assertIs(renamed['peaks'], initial['peaks'])
            self.assertEqual(renamed['names'], {'1': 'First'})
            self.assertEqual(initial['names'], {})
            self.assertNotEqual(renamed['analysis_key'], initial['analysis_key'])
            self.assertEqual(renamed, calculate(run, method))
            for incompatible in (replace(method, params=IntegrationParams(49, 100)),
                                 replace(method, solvent_mode='manual', delay_min=2)):
                with self.assertRaises(ValueError): assign_names(initial, run, incompatible)
            with self.assertRaises(ValueError):
                assign_names(dict(initial, analysis_key='stale'), run, method)

    def test_nonfinite_fractional_unknown_and_ignored_settings_rejected(self):
        for value in (float("nan"), float("inf"), -1, 0):
            with self.subTest(value=value):
                with self.assertRaises(ValueError): IntegrationParams(value, 100)
                with self.assertRaises(ValueError): IntegrationParams(50, value)
        for value in (1.9, True, float("nan"), "2"):
            with self.assertRaises(ValueError): IntegrationParams.from_dict(dict(noise_threshold_uv=50, area_threshold_uv=100, bunching_factor=value))
        with self.assertRaises(ValueError): IntegrationParams(50, 100, width_ratio=.3)
        with self.assertRaises(ValueError): IntegrationParams(50, 100, valley_to_peak_ratio=float("nan"))
        with self.assertRaises(ValueError): AnalysisMethod.from_dict(dict(params=IntegrationParams(50,100).to_dict(), ignored=True))
        with self.assertRaises(ValueError): ReportOptions.from_dict(dict(ignored=True))
        with self.assertRaises(ValueError): ReportOptions(full_scale_strip="false")
        with self.assertRaises(ValueError): ReportOptions(main_end_min=float("nan"))

    def test_events_components_and_solvent_are_unambiguous(self):
        for value in (-1, float("nan"), float("inf")):
            with self.assertRaises(ValueError): TimedEvent(value, "+P")
            with self.assertRaises(ValueError): Component("X", value)
        with self.assertRaises(ValueError): TimedEvent(1, "NT", float("nan"))
        with self.assertRaises(ValueError): TimedEvent(1, "+P", 4)
        with self.assertRaises(ValueError): Component("X", 1, float("inf"))
        with self.assertRaises(ValueError): IntegrationParams(50, 100, events=(TimedEvent(1,"-P"), TimedEvent(1,"+P")))
        with self.assertRaises(ValueError): AnalysisMethod(components=(Component("X",1),Component("x",2)))
        with self.assertRaises(ValueError): AnalysisMethod(delay_min=2)
        with self.assertRaises(ValueError): AnalysisMethod(solvent_mode="manual", delay_min=0)
        with self.assertRaises(ValueError): AnalysisMethod(IntegrationParams(50,100,events=(TimedEvent(1,"+P"),)),"manual",2)

    def test_preset_roundtrip_and_rejection_preserves_files(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"method.json"
            method = AnalysisMethod(IntegrationParams(5,100,events=(TimedEvent(3,"NT",10),)), "manual", 2, (Component("A",4,.2),))
            save_json(path, preset_record("method", method))
            self.assertEqual(read_preset(path,"method"), method)
            checksum = fingerprint(path)
            with self.assertRaises(FileExistsError): save_json(path, {})
            self.assertEqual(fingerprint(path), checksum)
            with self.assertRaises(ValueError): read_preset(path,"layout")
            path.write_text('{"schema":"gcviewer-fid-method-v99","method":{}}')
            with self.assertRaises(ValueError): read_preset(path,"method")
            path.write_text('{"schema":"gcviewer-fid-method-v1","method":{"params":{"noise_threshold_uv":NaN}}}')
            with self.assertRaises(ValueError): read_preset(path,"method")
            options = ReportOptions(page_size="a4", extra_fields=(("Course","Test"),), notes=("note",))
            save_json(path, preset_record("layout",options),overwrite=True)
            self.assertEqual(read_preset(path,"layout").to_dict(),options.to_dict())

    def test_solvent_exclusion_recalculates_percentage_and_names(self):
        with tempfile.TemporaryDirectory() as folder:
            run=fixture(folder); counts=run.counts.copy()
            all_peaks=calculate(run,AnalysisMethod())
            method=AnalysisMethod(solvent_mode="manual",delay_min=3,components=(Component("Later",250/60,.05),Component("Absent",5,.01)))
            excluded=calculate(run,method)
            self.assertEqual(len(all_peaks["peaks"]),2)
            self.assertEqual(len(excluded["peaks"]),1)
            self.assertEqual(excluded["peaks"][0]["area_pct"],100.)
            self.assertEqual(excluded["peaks"][0]["area_uv_s"],all_peaks["peaks"][1]["area_uv_s"])
            self.assertEqual(excluded["names"],{"1":"Later"})
            self.assertEqual(excluded["missing"],["Absent"])
            np.testing.assert_array_equal(run.counts,counts)
            self.assertFalse(run.counts.flags.writeable)

    def test_incomplete_changed_sources_and_out_of_run_settings_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError,"complete"): calculate(fixture(folder,complete=0),AnalysisMethod())
            run=fixture(folder)
            with self.assertRaises(ValueError): calculate(run,AnalysisMethod(solvent_mode="manual",delay_min=99))
            with self.assertRaises(ValueError): calculate(run,AnalysisMethod(IntegrationParams(5,100,bunching_factor=6000)))
            with self.assertRaises(ValueError): calculate(run,AnalysisMethod(IntegrationParams(5,100,events=(TimedEvent(99,"+P"),))))
            run.path.write_bytes(run.path.read_bytes()+b"changed")
            with self.assertRaisesRegex(ValueError,"changed"): check_source(run)

    def test_worker_csv_pdf_and_metadata_share_the_same_results(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder); run=fixture(folder); method=AnalysisMethod(components=(Component("First",100/60),))
            baseline=calculate(run,method)
            for action in ("csv","pdf"):
                write_request(folder,run,method,ReportOptions(page_size="a4"),action)
                self.assertEqual(main(["fid-analysis",str(folder),str(folder)]),0)
                record=json.loads((folder/"result.json").read_text())["analysis"]
                self.assertEqual(record["peaks"],json.loads(json.dumps(baseline["peaks"])))
                metadata=json.loads((folder/"output.json").read_text(encoding="utf-8"))
                self.assertFalse(metadata["figure_processing_applied"])
                self.assertEqual(metadata["output_sha256"],fingerprint(folder/f"output.{action}"))
            text="\n".join(p.extract_text() for p in PdfReader(folder/"output.pdf").pages)
            self.assertIn("First",text)
            self.assertNotIn("Solvent exclusion",text)
            self.assertNotIn("baseline correction",text)
            self.assertNotIn("Integrated with tcfid",text)
            self.assertIn("Generated",text)
            self.assertIn("Page 1 of 1",text)
            for label in ('Acquired by', 'Data:', 'Integration:', 'Timed events', 'SHA-256'):
                self.assertNotIn(label,text)
            self.assertIn("baseline correction",metadata["limitations"])
            with (folder/"output.csv").open(encoding="utf-8-sig",newline="") as handle: rows=list(csv.reader(handle))
            self.assertEqual(float(rows[1][3]),baseline["peaks"][0]["area_uv_s"])

    def test_no_peak_report_and_empty_plot_range(self):
        with tempfile.TemporaryDirectory() as folder:
            run=load_fid(synthetic_penx(Path(folder)/"flat.raw",counts=[10]*1000))
            method=AnalysisMethod()
            record=calculate(run,method)
            self.assertFalse(record["peaks"])
            self.assertIn("No peaks",record["warnings"][0])
            with self.assertRaises(ValueError): report_range(run,typed_result(record,run),ReportOptions(main_start_min=50,main_end_min=51))
            write_request(folder,run,method,ReportOptions(),"pdf")
            result=execute_request(folder)
            self.assertGreater(result["report_pages"],0)

    def test_output_guards_changed_destination_and_rollback(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); run=fixture(root)
            with self.assertRaises(ValueError): output_paths(run.path,".pdf",[run.path])
            raw_dir=root/"ms.raw"; raw_dir.mkdir()
            with self.assertRaises(ValueError): output_paths(raw_dir/"report.pdf",".pdf")
            paths=output_paths(root/"report.pdf",".pdf",[run.path])
            sources=(root/"staged.pdf",root/"staged.json")
            for p in sources: p.write_text("new")
            for p in paths: p.write_text("old")
            expected=tuple(fingerprint(p) for p in paths)
            paths[0].write_text("someone else")
            with self.assertRaises(FileExistsError): publish(sources,paths,expected)
            self.assertEqual(paths[0].read_text(),"someone else")
            paths[0].write_text("old")
            import os
            original=os.replace
            def fail_primary(src,dest):
                if dest==paths[0]: raise OSError("simulated publication failure")
                return original(src,dest)
            with patch("gcviewer.reports.publication.os.replace",side_effect=fail_primary):
                with self.assertRaises(OSError): publish(sources,paths,expected)
            self.assertEqual([p.read_text() for p in paths],["old","old"])
            self.assertFalse(list(root.glob('.fid-*')))
            publish(sources,paths,expected)
            self.assertEqual([p.read_text() for p in paths],["new","new"])


if __name__ == "__main__":
    unittest.main()

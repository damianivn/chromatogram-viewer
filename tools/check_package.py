"""Developer smoke for a packaged executable, with source/Python paths removed."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--spl", type=Path, help="Optional private reference SPL for the 74-row regression check")
    parser.add_argument("--ms-source", type=Path, help="Optional real GC-MS acquisition; read-only checks")
    parser.add_argument("--fid-source", type=Path, help="Optional real GC-FID acquisition for analysis/report checks")
    args = parser.parse_args()
    executable, output = args.exe.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    if os.name == "nt":
        env["PATH"] = os.environ["WINDIR"] + "\\System32;" + os.environ["WINDIR"]
    env["QT_QPA_PLATFORM"] = "offscreen"
    results = {}
    with tempfile.TemporaryDirectory(prefix="chromatogram-package-check-") as cwd:
        fixture = Path(cwd) / "synthetic-PENX.raw"
        from tests.penx_fixture import synthetic_penx
        synthetic_penx(fixture, counts=[-100, 0, 100, 500, 20], scale=(2., 4.), delay=.25)
        def run(name, arguments, expected=0):
            start = time.monotonic()
            result = subprocess.run([str(executable), *map(str, arguments)], cwd=cwd, env=env,
                capture_output=True, timeout=150 if args.ms_source else 120,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            results[name] = {"exit_code": result.returncode, "seconds": round(time.monotonic() - start, 3),
                             "stderr": result.stderr.decode(errors="replace")[-2000:]}
            assert result.returncode == expected, results[name]
        smoke_args = ["--smoke-output", output / "gui", "--fid-smoke-source", fixture]
        if args.ms_source:
            smoke_args.extend(["--ms-smoke-source", args.ms_source.resolve()])
        if args.fid_source:
            smoke_args.extend(["--fid-analysis-source", args.fid_source.resolve()])
        run("offscreen_gui", smoke_args)
        assert (output / "gui/smoke-ok.txt").is_file()
        assert (output / "gui/empty-workspace.png").is_file()
        results["empty_startup"] = "No sample/demo loaded; figure and data exports disabled before explicit test fixture injection."
        results["fid_ui"] = json.loads((output / "gui/fid/fid-checks.json").read_text())
        assert all(results["fid_ui"].values())
        if args.fid_source:
            results["fid_analysis"] = json.loads((output / "gui/fid-analysis/analysis-checks.json").read_text())
            assert results["fid_analysis"]["pdf_csv_table_agree"] and results["fid_analysis"]["cancellation_no_output"]
            assert all(results["fid_analysis"][key] for key in
                       ("names_reuse_integration", "home_restores_overview", "tables_fit_without_horizontal_scroll"))
        results["library_preferences"] = json.loads((output / "gui/library-preferences/preferences-checks.json").read_text())
        results["table_styling"] = json.loads((output / "gui/table-styling/table-checks.json").read_text())
        assert {"scientific-light", "scientific-dark"} == set(results["table_styling"])
        assert all(all(case.values()) for case in results["table_styling"].values())
        assert all(value is True for key, value in results["library_preferences"].items() if key != "scope")
        results["processing"] = json.loads((output / "gui/processing/processing-checks.json").read_text())
        assert results["processing"]["csv_original_values"] and results["processing"]["source_arrays_unchanged"]
        assert set(results["processing"]["cases"]) == {"individual", "overlay", "stacked", "spectrum"}
        results["comparisons"] = json.loads((output / "gui/comparisons/comparison-checks.json").read_text())
        assert results["comparisons"]["csv_all_points"] and results["comparisons"]["individual_report_preserved"]
        assert set(results["comparisons"]["modes"]) == {"overlay", "stacked"}
        for mode in ("overlay", "stacked"):
            for suffix in ("png", "pdf", "svg", "tif"):
                assert (output / f"gui/comparisons/{mode}.{suffix}").is_file()
        results["ms_inspection"] = json.loads((output / "gui/ms/inspection-checks.json").read_text())
        assert set(results["ms_inspection"]["selections"]) == {"eic", "single", "mean"}
        for mode in ("eic", "single", "mean"):
            for suffix in ("png", "pdf", "svg", "tif", "csv"):
                assert (output / f"gui/ms/{mode}.{suffix}").is_file()
                metadata = json.loads((output / f"gui/ms/{mode}.{suffix}.json").read_text())
                assert metadata["source_metadata"]["selection"] == results["ms_inspection"]["selections"][mode]
        from PIL import Image
        from pypdf import PdfReader
        typography = json.loads((output / "gui/demo.pdf.json").read_text())["typography"]
        page = PdfReader(output / "gui/demo.pdf").pages[0]
        assert "Synthetic demo" in page.extract_text()
        for font in page["/Resources"]["/Font"].values():
            font = font.get_object()
            assert font["/Subtype"] == "/Type0"
            assert "/FontFile2" in font["/DescendantFonts"][0].get_object()["/FontDescriptor"]
        assert "<text" in (output / "gui/demo.svg").read_text(encoding="utf-8")
        with Image.open(output / "gui/demo.tif") as raster:
            assert raster.format == "TIFF" and raster.info["dpi"] == (300, 300)
            assert raster.size == (int(180 / 25.4 * 300), int(110 / 25.4 * 300))
        results["figure_exports"] = {"pdf_embedded_fonts_and_text": "passed", "svg_editable_text": "passed",
                                     "tiff_size_and_dpi": "passed", "typography": typography}
        for mode in ("time", "signal", "both"):
            for suffix in ("png", "pdf", "svg", "tif"):
                path = output / f"gui/break-{mode}.{suffix}"
                assert path.is_file()
                metadata = json.loads(path.with_suffix(path.suffix + ".json").read_text(encoding="utf-8"))
                assert metadata["axis_breaks"]["x_omitted"] == ([4, 7] if mode != "signal" else None)
                assert metadata["axis_breaks"]["y_omitted"] == ([50, 70] if mode != "time" else None)
                assert metadata["annotations"][1]["hidden_by_axis_break"] == (mode != "signal")
                if suffix == "pdf":
                    page = PdfReader(path).pages[0]
                    assert "Retained peak" in page.extract_text()
                    assert ("Time-hidden peak" in page.extract_text()) == (mode == "signal")
                    assert not page.images
                elif suffix == "svg":
                    svg = path.read_text(encoding="utf-8")
                    assert ("x-axis-break" in svg) == (mode != "signal")
                    assert ("y-axis-break" in svg) == (mode != "time")
                    assert svg.count('id="x-axis-break"') == (2 if mode != "signal" else 0)
                    assert svg.count('id="y-axis-break"') == (2 if mode != "time" else 0)
        results["axis_break_exports"] = "X, Y and simultaneous breaks: four formats, metadata, retained/hidden annotations and vector marks passed."
        fid = output / "synthetic-fid-worker"
        fid.mkdir(exist_ok=True)
        run("synthetic_penx_worker", ["--load-worker", "fid", fixture, fid])
        result = json.loads((fid / "result.json").read_text())
        assert result["traces"][0]["instrument"] == "GC-FID"
        from gcviewer.services.worker import read_fid_result, read_result
        import numpy as np
        original = read_fid_result(fid)
        trace = read_result(fid)[0]
        np.testing.assert_array_equal(original.counts, [-100, 0, 100, 500, 20])
        np.testing.assert_array_equal(trace.signal, [-12.5, 0, 12.5, 62.5, 2.5])
        np.testing.assert_allclose(trace.time, .25 + np.arange(1, 6) / 750, rtol=0, atol=1e-15)
        assert trace.metadata["fid_acquisition"]["sha256"] == original.sha256
        assert not original.counts.flags.writeable
        results["fid_reader"] = {"reader_revision": trace.metadata["fid_acquisition"]["reader_revision"],
                                 "signed_counts_time_units_and_payload": "passed", "vendor_comparison": "pending owner data"}
        empty = Path(cwd) / "empty-synthetic-MS.raw"
        empty.mkdir()
        ms = output / "empty-ms-worker"
        ms.mkdir(exist_ok=True)
        run("empty_ms_worker_error", ["--load-worker", "ms", empty, ms], expected=1)
        assert "error" in json.loads((ms / "result.json").read_text())
        detail = output / "empty-ms-detail-worker"
        detail.mkdir(exist_ok=True)
        run("empty_ms_detail_error", ["--load-worker", "ms-detail", empty, detail], expected=1)
        assert "error" in json.loads((detail / "result.json").read_text())
        if args.spl:
            library = output / "spl-library-worker"
            library.mkdir(exist_ok=True)
            run("real_spl_library_worker", ["--library-worker", "ms", cwd, args.spl.resolve(), library])
            listing = json.loads((library / "library.json").read_text(encoding="utf-8"))
            assert len(listing["entries"]) == 74
            assert {"ADTP_CC7", "ADTP_SM1_2"}.issubset({r["name"] for r in listing["entries"]})
            assert "omitted: 70" in listing["list_warnings"][0]
            assert not any(row["available"] for row in listing["entries"])
        else:
            results["real_spl_library_worker"] = {"skipped": "No private reference SPL supplied"}
        fid_library = output / "fid-library-worker"
        fid_library.mkdir(exist_ok=True)
        run("synthetic_fid_library_worker", ["--library-worker", "fid", cwd, "", fid_library])
        listing = json.loads((fid_library / "library.json").read_text(encoding="utf-8"))
        available = [row for row in listing["entries"] if row["available"]]
        assert len(available) == 1 and available[0]["path"] == str(fixture)
        bad_library = output / "bad-library-worker"
        bad_library.mkdir(exist_ok=True)
        run("missing_library_error", ["--library-worker", "ms", Path(cwd) / "missing", "", bad_library], expected=1)
        assert "error" in json.loads((bad_library / "library.json").read_text())
        from tools.check_load_service import exercise_service
        results["warm_worker"] = exercise_service(executable,
            [("fid", fixture, True), ("fid", Path(cwd) / "missing.raw", False), ("fid", fixture, True)],
            output / "warm-worker")
        assert results["warm_worker"]["one_process"]
        requests = results["warm_worker"]["results"]
        assert requests[0]["npz_sha256"] == requests[2]["npz_sha256"]
    results["scope"] = "Offscreen GUI, synthetic signals, optional real SPL metadata and optional real GC-MS inspection on development PC; temporary working directory; Python variables removed; Windows-only PATH. Not clean lab-PC validation."
    results["package_bytes"] = sum(p.stat().st_size for p in executable.parent.rglob("*") if p.is_file())
    (output / "package-check.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()

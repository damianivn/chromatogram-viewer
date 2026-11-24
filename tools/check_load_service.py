"""Exercise the packaged warm worker from an unrelated directory, without Python paths."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time


def exercise_service(executable, requests, output, timeout=45):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    if os.name == "nt":
        env["PATH"] = os.environ["WINDIR"] + "\\System32;" + os.environ["WINDIR"]
    results = []
    with tempfile.TemporaryDirectory(prefix="warm-load-check-") as folder:
        control = Path(folder) / "control"
        control.mkdir()
        started = time.perf_counter()
        process = subprocess.Popen([str(Path(executable).resolve()), "--load-service", str(control)],
                                   cwd=folder, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            for i, (kind, source, succeeds) in enumerate(requests):
                job = output / f"request-{i}"
                job.mkdir(exist_ok=True)
                if (job / "result.json").exists():
                    raise ValueError("Use a fresh output directory for service verification")
                if i:
                    started = time.perf_counter()
                temporary = control / "request.tmp"
                temporary.write_text(json.dumps({"kind": kind, "source": str(source), "output": str(job)}), encoding="utf-8")
                temporary.replace(control / "request.json")
                while not (job / "result.json").exists():
                    if process.poll() is not None:
                        raise RuntimeError(f"Packaged service exited early: {process.returncode}")
                    if time.perf_counter() - started > timeout:
                        raise TimeoutError("Packaged load service did not finish")
                    time.sleep(.01)
                elapsed = time.perf_counter() - started
                record = json.loads((job / "result.json").read_text(encoding="utf-8"))
                assert ("error" not in record) == succeeds, record
                result = {"seconds": round(elapsed, 4), "success": succeeds, "pid": process.pid}
                if succeeds:
                    result["npz_sha256"] = hashlib.sha256((job / "traces.npz").read_bytes()).hexdigest()
                results.append(result)
            control.rmdir()
            assert process.wait(timeout=10) == 0
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
    return {"results": results, "total_seconds": round(sum(r["seconds"] for r in results), 4),
            "one_process": len({r["pid"] for r in results}) == 1,
            "scope": "Single development-host packaged-worker pass; source parsing and IPC included, UI rendering excluded. First request includes process startup. Not a cold-PC or Streamlit benchmark."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--folder", required=True, type=Path)
    parser.add_argument("--spl", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--count", type=int, default=4)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    from gcviewer.services.library import discover_library
    rows = [r for r in discover_library(args.folder, "ms", args.spl)["entries"] if r["available"]][:args.count]
    assert rows
    with tempfile.TemporaryDirectory(prefix="real-service-results-") as temporary:
        result = exercise_service(args.exe, [("ms", row["path"], True) for row in rows], temporary)
    if args.baseline:
        baseline = json.loads(args.baseline.read_text())
        assert [r["npz_sha256"] for r in baseline["results"]] == [r["npz_sha256"] for r in result["results"]], "Source trace results differ from baseline"
        result["baseline_trace_bytes_identical"] = True
        result["baseline_seconds"] = baseline["total_seconds"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

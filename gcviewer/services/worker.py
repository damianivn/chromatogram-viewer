"""Owned child process: lightweight traces or on-demand mass-function matrices.

NPZ arrays plus JSON are used instead of executable pickle payloads.
"""
from dataclasses import fields
import json
from pathlib import Path
import sys
import time
import numpy as np
from gcviewer.data_models.acquisition import Trace


def write_result(directory, traces, fid_run=None):
    directory = Path(directory)
    records = []
    arrays = {}
    for i, trace in enumerate(traces):
        records.append({f.name: getattr(trace, f.name) for f in fields(trace) if f.name not in ("time", "signal")})
        arrays[f"t{i}"] = trace.time
        arrays[f"s{i}"] = trace.signal
    np.savez(directory / "traces.npz", **arrays)
    record = {"traces": records}
    if fid_run is not None:
        from gcviewer.services.fid_acquisition import run_record
        np.savez(directory / "fid-counts.npz", counts=fid_run.counts)
        record["fid_acquisition"] = run_record(fid_run)
    write_record(directory, record)


def write_record(directory, record):
    temporary = Path(directory) / "result.tmp"
    temporary.write_text(json.dumps(record, default=str), encoding="utf-8")
    temporary.replace(Path(directory) / "result.json")


def read_result(directory):
    directory = Path(directory)
    result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
    if "error" in result:
        raise ValueError(result["error"])
    with np.load(directory / "traces.npz", allow_pickle=False) as arrays:
        return [Trace(**record, time=arrays[f"t{i}"], signal=arrays[f"s{i}"])
                for i, record in enumerate(result["traces"])]


def read_fid_result(directory):
    from gcviewer.services.fid_acquisition import restore_run
    directory = Path(directory)
    result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
    if "fid_acquisition" not in result:
        raise ValueError("The FID loader did not return its original acquisition data.")
    with np.load(directory / "fid-counts.npz", allow_pickle=False) as arrays:
        return restore_run(result["fid_acquisition"], arrays["counts"])


def main(args):
    from gcviewer.services.acquisition import load_source
    kind, source, output = args
    try:
        if kind == "fid-analysis":
            from gcviewer.services.fid_workflow import execute_request
            write_record(output, {"analysis": execute_request(source)})
        elif kind == "fid-batch":
            from gcviewer.services.fid_batch import execute_batch
            write_record(output, {"batch": execute_batch(source)})
        elif kind == "ms-detail":
            from gcviewer.parsers.waters import load_raw
            from gcviewer.analysis.mass_spectra import ms_functions
            path = Path(source).resolve()
            if path.suffix.lower() != ".raw" or not path.is_dir():
                raise ValueError("GC-MS needs a .raw acquisition directory.")
            write_ms_result(output, ms_functions(load_raw(str(path)), path))
        elif kind == "fid":
            from gcviewer.services.acquisition import load_fid, fid_trace
            run = load_fid(source)
            write_result(output, [fid_trace(run)], fid_run=run)
        else:
            write_result(output, load_source(source, kind))
        return 0
    except Exception as exc:
        write_record(output, {"error": f"{type(exc).__name__}: {exc}"})
        return 1


def write_ms_result(directory, functions):
    arrays, records = {}, []
    for i, function in enumerate(functions):
        records.append({f.name: getattr(function, f.name) for f in fields(function)
                        if f.name not in ("time", "masses", "data")})
        for name in ("time", "masses", "data"):
            arrays[f"{name}{i}"] = getattr(function, name)
    np.savez(Path(directory) / "functions.npz", **arrays)
    write_record(directory, {"functions": records})


def read_ms_result(directory):
    from gcviewer.data_models.spectra import MSFunction
    directory = Path(directory)
    result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
    if "error" in result:
        raise ValueError(result["error"])
    with np.load(directory / "functions.npz", allow_pickle=False) as arrays:
        return [MSFunction(**record, **{name: arrays[f"{name}{i}"] for name in ("time", "masses", "data")})
                for i, record in enumerate(result["functions"])]


def serve(directory):
    """Serial warm worker. File IPC also works with windowless pythonw/EXEs."""
    request_path = Path(directory) / "request.json"
    while Path(directory).is_dir():
        if not request_path.exists():
            time.sleep(.025)
            continue
        request = json.loads(request_path.read_text(encoding="utf-8"))
        request_path.unlink()
        main([request["kind"], request["source"], request["output"]])
    return 0


if __name__ == "__main__":
    sys.exit(serve(sys.argv[2]) if sys.argv[1:2] == ["--serve"] else main(sys.argv[1:]))

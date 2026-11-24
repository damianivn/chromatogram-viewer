"""Independent FID analysis documents, validated presets and worker records."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from gcviewer.analysis.retention_names import Component, identify
from gcviewer.analysis.totalchrom_fid import IntegrationParams, TimedEvent, integrate
from gcviewer.analysis.totalchrom_fid import CLIPPING_WARNING, IntegrationResult, Peak, integrate_skipping_solvent
from gcviewer.services.fid_acquisition import run_record, restore_run

if TYPE_CHECKING:
    from gcviewer.reports.fid_pdf import ReportOptions

from gcviewer.revisions import FID_ANALYSIS_REVISION

ANALYSIS_REVISION = FID_ANALYSIS_REVISION
LIMITATIONS = ("Retention-time names are assignments, not confirmed identities. "
               "Areas are not calibrated concentrations. Automatic boundaries can differ from TotalChrom; "
               "small peaks can show larger relative differences. Skimming, negative peaks and baseline correction are not supported.")


def strict_keys(value, allowed, label):
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise ValueError(f"Unsupported {label} fields or invalid object.")


@dataclass(frozen=True)
class AnalysisMethod:
    params: IntegrationParams = field(default_factory=lambda: IntegrationParams(50., 100.))
    solvent_mode: str = "include"
    delay_min: float = 0.
    components: tuple[Component, ...] = ()

    def __post_init__(self):
        if self.solvent_mode not in ("include", "manual", "automatic"):
            raise ValueError("Choose include, manual delay or automatic solvent exclusion.")
        if not math.isfinite(self.delay_min) or self.delay_min < 0:
            raise ValueError("Solvent delay must be finite and nonnegative.")
        if self.solvent_mode != "manual" and self.delay_min != 0:
            raise ValueError("A delay value is only used with manual solvent exclusion.")
        if self.solvent_mode == "manual" and self.delay_min <= 0:
            raise ValueError("Manual solvent delay must be greater than zero.")
        names = [c.name.strip().casefold() for c in self.components]
        if len(set(names)) != len(names):
            raise ValueError("Component names must be unique.")
        if self.solvent_mode == "manual" and any(e.kind in ("-P", "+P") and e.time_min <= self.delay_min for e in self.params.events):
            raise ValueError("Detection events must follow the manual solvent delay; use Include all for a fully custom schedule.")

    def to_dict(self):
        return {"params": self.params.to_dict(), "solvent_mode": self.solvent_mode,
                "delay_min": self.delay_min, "components": [c.to_dict() for c in self.components]}

    @classmethod
    def from_dict(cls, value):
        strict_keys(value, ("params", "solvent_mode", "delay_min", "components"), "method")
        p = value["params"]
        strict_keys(p, IntegrationParams.__dataclass_fields__, "integration")
        for event in p.get("events", []):
            strict_keys(event, TimedEvent.__dataclass_fields__, "event")
        for component in value.get("components", []):
            strict_keys(component, Component.__dataclass_fields__, "component")
        return cls(IntegrationParams.from_dict(p), value.get("solvent_mode", "include"),
                   float(value.get("delay_min", 0)), tuple(Component.from_dict(c) for c in value.get("components", [])))

    def validate_run(self, run):
        end = float(run.times_min[-1])
        if run.header.file_complete_flag != 3:
            raise ValueError("This acquisition is not marked complete. Reopen it after acquisition finishes before integrating or reporting.")
        if self.params.bunching_factor > run.n_points // 2:
            raise ValueError("Bunching must leave at least two groups of recorded points.")
        if self.delay_min >= end or any(e.time_min > end for e in self.params.events):
            raise ValueError("Solvent delay and timed events must fall within the acquisition.")
        if any(c.rt_min > end for c in self.components):
            raise ValueError("Expected component retention times must fall within this acquisition.")


def default_layout():
    from gcviewer.reports.fid_pdf import ReportOptions
    return ReportOptions()


@dataclass
class AnalysisDocument:
    method: AnalysisMethod = field(default_factory=AnalysisMethod)
    layout: ReportOptions = field(default_factory=default_layout)
    result: dict | None = None
    draft: dict | None = None


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def analysis_key(run, method):
    return digest({"source": run.sha256, "method": method.to_dict(), "revision": ANALYSIS_REVISION})


def integration_key(run, method):
    """Names label an existing result; they never affect numerical boundaries."""
    return analysis_key(run, replace(method, components=()))


def assign_names(record, run, method):
    """Relabel verified numerical results without invoking integration."""
    previous = AnalysisMethod.from_dict(record["method"])
    if (record["analysis_key"] != analysis_key(run, previous)
            or integration_key(run, previous) != integration_key(run, method)):
        raise ValueError("Integrate the current settings before assigning names.")
    method.validate_run(run)
    names, missing = identify(typed_result(record, run), method.components)
    return dict(record, method=method.to_dict(), analysis_key=analysis_key(run, method),
                names={str(k): v for k, v in names.items()}, missing=missing)


def check_source(run):
    if run.path is None or not run.path.is_file() or hashlib.sha256(run.path.read_bytes()).hexdigest() != run.sha256:
        raise ValueError("The source acquisition changed or is no longer available. Reopen it before analysis or export.")


def calculate(run, method):
    method.validate_run(run)
    params = method.params
    delay = None
    if method.solvent_mode == "automatic":
        result, delay = integrate_skipping_solvent(run, params)
    else:
        if method.solvent_mode == "manual":
            delay = method.delay_min
            params = replace(params, events=(TimedEvent(0., "-P"), TimedEvent(delay, "+P")) + params.events)
        result = integrate(run, params)
    names, missing = identify(result, method.components)
    warnings = list(run.warnings) + list(result.warnings)
    if any(p.clipped for p in result.peaks):
        warnings.append(CLIPPING_WARNING)
    if not result.peaks:
        warnings.append("No peaks met the chosen integration settings.")
    if method.solvent_mode == "automatic" and delay is None:
        warnings.append("Automatic solvent exclusion found no candidate; all detected peaks remain included.")
    if method.solvent_mode == "automatic" and delay is not None:
        warnings.append("Automatic solvent exclusion uses a peak-height/clipping heuristic; inspect the effective delay.")
    return {"schema": "gcviewer-fid-result-v1", "analysis_key": analysis_key(run, method),
            "method": method.to_dict(), "effective_params": result.params.to_dict(),
            "effective_delay_min": delay, "peaks": [asdict(p) for p in result.peaks],
            "names": {str(k): v for k, v in names.items()}, "missing": missing,
            "warnings": warnings, "total_area_uv_s": result.total_area_uv_s,
            "area_percent_denominator": "Sum of included integrated peak areas; excluded intervals do not contribute.",
            "units": {"area": "uV*s", "height": "uV", "time": "min"}}


def typed_result(record, run):
    peaks = []
    for value in record["peaks"]:
        value = dict(value, baseline_counts=tuple(value["baseline_counts"]), flags=tuple(value["flags"]))
        peaks.append(Peak(**value))
    return IntegrationResult(tuple(peaks), IntegrationParams.from_dict(record["effective_params"]),
                             run.uv_per_count, tuple(record["warnings"]))


def report_range(run, result, options):
    from gcviewer.figures.fid_plot import main_view_range
    lo, hi = main_view_range(run, result, options.hide_solvent)
    lo = options.main_start_min if options.main_start_min is not None else lo
    hi = options.main_end_min if options.main_end_min is not None else hi
    if lo >= hi or not np.any((run.times_min >= lo) & (run.times_min <= hi)):
        raise ValueError("The report plot range contains no data. Widen it or leave the limits blank.")
    return lo, hi


def preset_record(kind, value):
    return {"schema": f"gcviewer-fid-{kind}-v1", kind: value.to_dict()}


def read_preset(path, kind):
    from gcviewer.reports.fid_pdf import ReportOptions
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"),
                       parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"Nonfinite JSON value: {value}")))
    strict_keys(value, ("schema", kind), "preset")
    if value.get("schema") != f"gcviewer-fid-{kind}-v1":
        raise ValueError("Unsupported preset type or schema version.")
    return (AnalysisMethod if kind == "method" else ReportOptions).from_dict(value[kind])


def write_request(folder, run, method, layout, action):
    np.savez(Path(folder) / "counts.npz", counts=run.counts)
    record = {"run": run_record(run), "method": method.to_dict(), "layout": layout.to_dict(), "action": action}
    (Path(folder) / "request.json").write_text(json.dumps(record, allow_nan=False), encoding="utf-8")


def execute_request(folder):
    """Executed in the owned worker. Only temporary files are written here."""
    folder = Path(folder)
    request = json.loads((folder / "request.json").read_text(encoding="utf-8"))
    with np.load(folder / "counts.npz", allow_pickle=False) as arrays:
        run = restore_run(request["run"], arrays["counts"])
    method = AnalysisMethod.from_dict(request["method"])
    check_source(run)
    (folder / "progress.txt").write_text("Integrating original acquisition…", encoding="utf-8")
    record = calculate(run, method)
    action = request["action"]
    if action not in ("integrate", "pdf", "csv"):
        raise ValueError("Unknown FID analysis operation.")
    if action != "integrate":
        from gcviewer.reports.fid_pdf import ReportEntry, ReportOptions, write_report
        options = ReportOptions.from_dict(request["layout"])
        typed = typed_result(record, run)
        (folder / "progress.txt").write_text("Preparing report…" if action == "pdf" else "Preparing peak table…", encoding="utf-8")
        if action == "pdf":
            report_range(run, typed, options)
            notes = options.notes
            if record["effective_delay_min"] is not None:
                notes += (f"Solvent excluded before {record['effective_delay_min']:.6g} min; area % uses included peaks.",)
            info = write_report(folder / "output.pdf", ReportEntry(run, typed,
                {int(k): v for k, v in record["names"].items()}, record["missing"]), replace(options, notes=notes))
            record["report_pages"] = info.pages
        else:
            from gcviewer.reports.fid_numeric import write_peak_csv
            write_peak_csv(folder / "output.csv", typed, record["names"])
        metadata = {"schema": "gcviewer-fid-analysis-export-v1", "revision": ANALYSIS_REVISION,
                    "generated_utc": datetime.now(timezone.utc).isoformat(), "acquisition": run_record(run),
                    "analysis": record, "report_layout": options.to_dict(), "limitations": LIMITATIONS,
                    "figure_processing_applied": False, "output_sha256": hashlib.sha256((folder / f"output.{action}").read_bytes()).hexdigest()}
        (folder / "output.json").write_text(json.dumps(metadata, indent=2, allow_nan=False, ensure_ascii=False), encoding="utf-8")
    check_source(run)
    return record

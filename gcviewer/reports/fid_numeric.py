"""Peak-table CSV export from completed integration results."""
import csv


def write_peak_csv(path, result, names):
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Peak", "Assigned component", "Retention time (min)", "Area (µV·s)", "Height (µV)", "Area (%)", "Start (min)", "End (min)", "Baseline", "Clipped", "Flags"])
        for p in result.peaks:
            writer.writerow([p.number, names.get(str(p.number), ""), p.rt_min, p.area_uv_s,
                             p.height_uv, p.area_pct, p.start_min, p.end_min, p.baseline_code, p.clipped, " ".join(p.flags)])

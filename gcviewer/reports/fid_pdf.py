"""PDF reports for integrated TotalChrom FID runs, using matplotlib only.

``write_report(path, entries, options)`` writes one PDF:

* one run: that run's page(s);
* several runs: a summary page (one row per run), then each run's page(s).

A run page holds a header block of details (fields and labels chosen in ReportOptions),
the chromatogram (a full-scale strip plus a main view that starts after the solvent peak
and is fitted to the unclipped peaks), the peak table (continued on further pages when
long) and notes. Every page has a running header and a generated date/time and
page-number footer. Optional custom footer text appears below that line.

Rendering uses an rc_context; callers must isolate concurrent rendering in an
owned process because Matplotlib configuration is process-global.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import textwrap
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Callable, Mapping, NamedTuple, Sequence

import matplotlib
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure
from matplotlib.transforms import blended_transform_factory
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle

from gcviewer.revisions import TOTALCHROM_VERSION
from gcviewer.analysis.totalchrom_fid import CLIPPING_WARNING, IntegrationResult, find_solvent_peak
from gcviewer.figures.fid_plot import PEAK_LABEL_MODES, detection_off_windows, main_view_range, plot_chromatogram
from gcviewer.data_models.totalchrom import RawRun

PAGE_SIZES = {"letter": (8.5, 11.0), "a4": (8.27, 11.69)}
MARGIN_X, MARGIN_TOP, MARGIN_BOTTOM = 0.6, 0.5, 0.75
RUNNING_HEADER = 0.42
ROW_H, HEAD_H, LINE_H = 0.19, 0.26, 0.17
EPS = 1e-6
CHARS_PER_INCH = 17.0
RC = {"pdf.fonttype": 42, "font.family": "DejaVu Sans", "font.size": 8,
      "axes.labelsize": 8, "xtick.labelsize": 7, "ytick.labelsize": 7,
      "axes.linewidth": 0.6, "xtick.major.width": 0.6, "ytick.major.width": 0.6}


DEFAULT_FIELD_KEYS = ("sample", "study", "sample_number", "vial", "injected",
                      "sequence", "file", "instrument", "method")


@dataclass(frozen=True)
class ReportOptions:
    title: str = "Chromatography report"
    subtitle: str = ""
    page_size: str = "letter"
    heading: str = "sample"
    heading_time: bool = True
    header_fields: tuple[tuple[str, str], ...] | None = None
    extra_fields: tuple[tuple[str, str], ...] = ()
    full_scale_strip: bool = True
    hide_solvent: bool = True
    main_start_min: float | None = None
    main_end_min: float | None = None
    zoom_to_peaks: bool = True
    peak_labels: str = "name_or_rt"
    legend: bool = True
    minor_ticks: bool = True
    x_label: str = "Time (min)"
    y_label: str = "Response (mV)"
    peak_table_new_page: bool = False
    notes: tuple[str, ...] = ()
    disclaimer: str = ""

    def __post_init__(self) -> None:
        for name in ("main_start_min", "main_end_min"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
                raise ValueError(f"{name} must be finite and nonnegative")
        for name in ("heading_time", "full_scale_strip", "hide_solvent", "zoom_to_peaks", "legend", "minor_ticks", "peak_table_new_page"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be true or false")
        for name in ("title", "subtitle", "heading", "page_size", "peak_labels", "x_label", "y_label", "disclaimer"):
            if not isinstance(getattr(self, name), str):
                raise ValueError(f"{name} must be text")
        for rows in (self.header_fields or (), self.extra_fields):
            if any(len(row) != 2 or not all(isinstance(value, str) for value in row) for row in rows):
                raise ValueError("report fields must be pairs of text values")
        if isinstance(self.notes, str) or any(not isinstance(note, str) for note in self.notes):
            raise ValueError("notes must be a list of text lines")
        if self.page_size.lower() not in PAGE_SIZES:
            raise ValueError(f"page_size must be one of {sorted(PAGE_SIZES)}")
        if self.peak_labels not in PEAK_LABEL_MODES:
            raise ValueError(f"peak_labels must be one of {PEAK_LABEL_MODES}")
        if self.heading and self.heading not in HEADER_FIELDS:
            raise ValueError(f"unknown heading field {self.heading!r}")
        for key, _label in self.fields():
            if key not in HEADER_FIELDS:
                raise ValueError(f"unknown header field {key!r}; known: {sorted(HEADER_FIELDS)}")
        if (self.main_start_min is not None and self.main_end_min is not None
                and self.main_end_min <= self.main_start_min):
            raise ValueError("main_end_min must be after main_start_min")

    def fields(self) -> tuple[tuple[str, str], ...]:
        if self.header_fields is None:
            return tuple((k, HEADER_FIELDS[k][0]) for k in DEFAULT_FIELD_KEYS)
        return tuple(self.header_fields)

    def to_dict(self) -> dict:
        """Plain types only (JSON-safe), e.g. to save the lab's report layout."""
        d = {f: getattr(self, f) for f in self.__dataclass_fields__}
        d["header_fields"] = [list(x) for x in self.fields()]
        d["extra_fields"] = [list(x) for x in self.extra_fields]
        d["notes"] = list(self.notes)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ReportOptions":
        unknown = set(d) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError(f"unsupported report options: {sorted(unknown)}")
        d = dict(d)
        for k in ("header_fields", "extra_fields"):
            if d.get(k) is not None:
                d[k] = tuple(tuple(x) for x in d[k])
        if "notes" in d:
            d["notes"] = tuple(d["notes"])
        return cls(**d)


@dataclass(frozen=True)
class ReportEntry:
    run: RawRun
    result: IntegrationResult
    names: Mapping[int, str] = field(default_factory=dict)
    missing: Sequence[str] = ()
    notes: Sequence[str] = ()


class ReportInfo(NamedTuple):
    path: Path
    pages: int


@dataclass(frozen=True)
class _Col:
    header: str
    width: float
    align: str = "left"
    fmt: Callable[[object], str] = str


@dataclass
class _Fixed:
    height: float
    draw: Callable[["_Page", float], None]


@dataclass
class _Table:
    cols: list[_Col]
    rows: list[list]
    title: str = ""
    empty_text: str = "(none)"


@dataclass
class _Lines:
    lines: list[tuple[str, dict]]


@dataclass
class _Break:
    """Start a new page (same section)."""


class _Page:
    def __init__(self, size: tuple[float, float]) -> None:
        self.w, self.h = size
        self.fig = Figure(figsize=size)
        FigureCanvasAgg(self.fig)
        self.plot_axes: list = []

    def text(self, x: float, y: float, s: str, **kw) -> None:
        kw.setdefault("va", "top")
        kw.setdefault("fontsize", 8)
        self.fig.text(x / self.w, 1 - y / self.h, s, **kw)

    def axes(self, x: float, y: float, w: float, h: float):
        return self.fig.add_axes((x / self.w, 1 - (y + h) / self.h, w / self.w, h / self.h))

    def hline(self, y: float, color: str = "0.65", lw: float = 0.6) -> None:
        self.fig.add_artist(Line2D([MARGIN_X / self.w, 1 - MARGIN_X / self.w], [1 - y / self.h] * 2,
                                   transform=self.fig.transFigure, color=color, lw=lw))


def _fit(s: str, width_in: float) -> str:
    n = max(4, int(width_in * CHARS_PER_INCH))
    return s if len(s) <= n else s[: n - 1] + "…"


def _fit_middle(s: str, width_in: float) -> str:
    n = max(8, int(width_in * CHARS_PER_INCH))
    if len(s) <= n:
        return s
    keep = n - 1
    return s[: keep // 2] + "…" + s[len(s) - (keep - keep // 2):]


def _draw_table(page: _Page, x: float, y: float, table: _Table, rows: list[list], title: str) -> float:
    width = sum(c.width for c in table.cols)
    top = y
    if title:
        page.text(x, y, title, fontsize=8.5, fontweight="bold")
        top += LINE_H + 0.03
    n_rows = max(len(rows), 1)
    h = HEAD_H + ROW_H * n_rows
    ax = page.axes(x, top, width, h)
    ax.set_xlim(0, width)
    ax.set_ylim(h, 0)
    ax.set_axis_off()

    def cell_x(cx: float, c: _Col) -> float:
        return cx + c.width - 0.06 if c.align == "right" else cx + 0.06

    cx = 0.0
    for c in table.cols:
        ax.text(cell_x(cx, c), HEAD_H / 2, c.header, ha=c.align, va="center",
                fontsize=7.5, fontweight="bold")
        cx += c.width
    ax.plot([0, width], [HEAD_H, HEAD_H], color="0.25", lw=0.8)
    if not rows:
        ax.text(0.06, HEAD_H + ROW_H / 2, table.empty_text, va="center", fontsize=7.5, color="0.4")
    for r, row in enumerate(rows):
        y0 = HEAD_H + r * ROW_H
        if r % 2:
            ax.add_patch(Rectangle((0, y0), width, ROW_H, color="0.955", lw=0, zorder=0))
        cx = 0.0
        for c, value in zip(table.cols, row):
            blank = value is None or (value == "" and c.align == "right")
            text = "–" if blank else c.fmt(value)
            if c.align == "left":
                text = _fit(text, c.width - 0.1)
            ax.text(cell_x(cx, c), y0 + ROW_H / 2, text, ha=c.align, va="center", fontsize=7.5)
            cx += c.width
    ax.plot([0, width], [h, h], color="0.65", lw=0.6)
    return top + h


def _paginate(sections: list[tuple[str, list]], size: tuple[float, float]) -> list[dict]:
    """Lay out sections (each starts a page) into pages of drawing operations."""
    _w, h = size
    top, bottom = MARGIN_TOP + RUNNING_HEADER, h - MARGIN_BOTTOM
    pages: list[dict] = []

    def new_page(context: str) -> dict:
        pages.append({"context": context, "ops": []})
        return pages[-1]

    for context, items in sections:
        page, y = new_page(context), top
        for item in items:
            if isinstance(item, _Break):
                if page["ops"]:
                    page, y = new_page(context), top
                continue
            if isinstance(item, _Fixed):
                if y + item.height > bottom + EPS and page["ops"]:
                    page, y = new_page(context), top
                page["ops"].append(("fixed", y, item))
                y += item.height
            elif isinstance(item, _Lines):
                for text, style in item.lines:
                    if y + LINE_H > bottom + EPS:
                        page, y = new_page(context), top
                    page["ops"].append(("line", y, (text, style)))
                    y += LINE_H
            elif isinstance(item, _Table):
                rows, first = list(item.rows), True
                title_h = (LINE_H + 0.03) if item.title else 0.0
                while True:
                    fit = int((bottom + EPS - y - title_h - HEAD_H) // ROW_H)
                    if fit < min(3, max(len(rows), 1)):
                        page, y = new_page(context), top
                        fit = int((bottom - y - title_h - HEAD_H) // ROW_H)
                    chunk, rows = rows[:fit], rows[fit:]
                    title = item.title if first else (item.title + " (continued)" if item.title else "")
                    page["ops"].append(("table", y, (item, chunk, title)))
                    y += title_h + HEAD_H + ROW_H * max(len(chunk), 1) + 0.18
                    first = False
                    if not rows:
                        break
    return pages


def _local(dt: datetime, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return dt.astimezone().strftime(fmt)


def _events_text(result: IntegrationResult) -> str:
    if not result.params.events:
        return "none"
    return ", ".join(f"{e.kind} {e.time_min:.3f} min" + (f" = {e.value:g} µV" if e.value else "")
                     for e in result.params.events)


def _settings_text(result: IntegrationResult) -> str:
    p = result.params
    return (f"NT {p.noise_threshold_uv:g} µV, AT {p.area_threshold_uv:g} µV, BF {p.bunching_factor}, "
            f"V/P {p.valley_to_peak_ratio:g}")


def _run_label(entry: ReportEntry) -> str:
    run = entry.run
    name = run.header.sample_name or "(no sample name)"
    return f"{name}  ·  {run.path.name if run.path else ''}"


def _sequence_text(e: ReportEntry) -> str:
    h = e.run.header
    seq = PureWindowsPath(h.sequence_path).name if h.sequence_path else "–"
    return f"{seq} (row {h.sequence_row + 1})"


def _solvent_text(e: ReportEntry) -> str:
    sol = find_solvent_peak(e.result)
    if sol is not None:
        return f"{sol.rt_min:.3f} min" + (", clipped at the A/D limit" if sol.clipped else "")
    t_end = float(e.run.times_min[-1])
    windows = detection_off_windows(e.result.params.events, t_end)
    if windows and windows[0][0] <= float(e.run.times_min[0]) + 1e-9:
        return f"skipped (detection off until {windows[0][1]:.3f} min)"
    return "none found"


def _components_text(e: ReportEntry) -> str:
    found = [e.names[p.number] for p in e.result.peaks if p.number in e.names]
    text = ", ".join(found) if found else "none named"
    return text + (f"; not found: {', '.join(e.missing)}" if e.missing else "")


def _data_text(e: ReportEntry) -> str:
    r = e.run
    return f"{r.n_points} points, {r.rate_hz:g} Hz, {r.header.run_time_min:.2f} min"


HEADER_FIELDS: dict[str, tuple[str, Callable[[ReportEntry], str]]] = {
    "sample": ("Sample", lambda e: e.run.header.sample_name or "–"),
    "study": ("Study", lambda e: e.run.header.study or "–"),
    "sample_number": ("Sample no.", lambda e: e.run.header.sample_number or "–"),
    "vial": ("Vial", lambda e: str(e.run.header.vial)),
    "injected": ("Injected", lambda e: _local(e.run.header.injection_utc)),
    "acquired_by": ("Acquired by", lambda e: e.run.header.acquired_by or "–"),
    "sequence": ("Sequence", _sequence_text),
    "file": ("File", lambda e: e.run.path.name if e.run.path else "–"),
    "instrument": ("Instrument", lambda e: f"{e.run.header.instrument_name}, channel {e.run.header.channel}"),
    "method": ("Method", lambda e: PureWindowsPath(e.run.header.instrument_method).name or "–"),
    "data": ("Data", _data_text),
    "integration": ("Integration", lambda e: _settings_text(e.result)),
    "timed_events": ("Timed events", lambda e: _events_text(e.result)),
    "solvent": ("Solvent peak", _solvent_text),
    "components": ("Components", _components_text),
    "sha256": ("SHA-256", lambda e: e.run.sha256[:24] + "…" if e.run.sha256 else "–"),
}


def header_items(entry: ReportEntry, options: ReportOptions) -> list[tuple[str, str]]:
    """(label, value) lines of a run's header block, in order."""
    items = [(label, HEADER_FIELDS[key][1](entry)) for key, label in options.fields()]
    return items + [(label, value) for label, value in options.extra_fields]


def _run_header(entry: ReportEntry, usable_w: float, options: ReportOptions) -> _Fixed:
    hd = entry.run.header
    items = header_items(entry, options)
    half = (len(items) + 1) // 2
    columns = (items[:half], items[half:])
    heading = ""
    if options.heading:
        heading = HEADER_FIELDS[options.heading][1](entry)
        if heading in ("", "–"):
            heading = entry.run.path.stem if entry.run.path else "Run"
    head_h = 0.34 if (heading or options.heading_time) else 0.0
    height = head_h + half * LINE_H + (0.12 if items else 0.0)

    def draw(page: _Page, y: float) -> None:
        if heading:
            page.text(MARGIN_X, y, heading, fontsize=13, fontweight="bold")
        if options.heading_time:
            page.text(page.w - MARGIN_X, y + 0.04,
                      f"injected {_local(hd.injection_utc, '%Y-%m-%d %H:%M')}",
                      fontsize=8, ha="right", color="0.3")
        col_w = usable_w / 2
        label_w = min(1.25, max([0.6] + [len(lb) / CHARS_PER_INCH + 0.15 for lb, _ in items]))
        for col, rows in enumerate(columns):
            x = MARGIN_X + col * col_w
            for i, (label, value) in enumerate(rows):
                yy = y + head_h + i * LINE_H
                page.text(x, yy, _fit(label, label_w - 0.05), color="0.35")
                page.text(x + label_w, yy, _fit_middle(str(value), col_w - label_w - 0.1))
        page.hline(y + height - 0.05)

    return _Fixed(height, draw)


def _unit(label: str) -> str:
    """'Response (mV)' -> 'mV' for the short full-scale strip."""
    if "(" in label and label.endswith(")"):
        return label[label.rindex("(") + 1:-1]
    return label


def _plot_block(entry: ReportEntry, usable_w: float, height: float, options: ReportOptions,
                strip: bool) -> _Fixed:
    def draw(page: _Page, y: float) -> None:
        ax = page.axes(MARGIN_X + 0.55, y + 0.12, usable_w - 0.55, height - 0.52)
        page.plot_axes.append(ax)
        run = entry.run
        t = run.times_min
        if strip:
            plot_chromatogram(ax, run, entry.result, entry.names,
                              x_range=(float(t[0]), float(t[-1])), peak_labels="none",
                              legend=options.legend, x_label="", y_label=_unit(options.y_label),
                              minor_ticks=options.minor_ticks, linewidth=0.6)
            ax.text(0.005, 0.95, "full scale", transform=ax.transAxes, va="top", fontsize=7,
                    color="0.4")
        else:
            x0, x1 = main_view_range(run, entry.result, options.hide_solvent)
            if options.main_start_min is not None:
                x0 = options.main_start_min
            if options.main_end_min is not None:
                x1 = options.main_end_min
            plot_chromatogram(ax, run, entry.result, entry.names, x_range=(x0, x1),
                              zoom_to_peaks=options.zoom_to_peaks, peak_labels=options.peak_labels,
                              legend=options.legend, x_label=options.x_label,
                              y_label=options.y_label, minor_ticks=options.minor_ticks,
                              label_size=7)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)

    return _Fixed(height, draw)


def _align_plot_axes(page: _Page) -> None:
    """Line the plots up with the text: every y-axis label starts exactly at the left margin,
    all plots share one left spine (just clear of the widest tick labels) and the right spine
    sits on the right margin."""
    axes = page.plot_axes
    if not axes:
        return
    fig = page.fig
    renderer = fig.canvas.get_renderer()
    dpi = fig.dpi
    fig_w_px = page.w * dpi
    right = 1.0 - MARGIN_X / page.w
    label_w = max((ax.yaxis.label.get_window_extent(renderer).width
                   for ax in axes if ax.yaxis.label.get_text()), default=0.0)
    label_right_px = MARGIN_X * dpi + label_w
    for ax in axes:
        if ax.yaxis.label.get_text():
            ax.yaxis.set_label_coords(label_right_px / fig_w_px, 0.5,
                                      transform=blended_transform_factory(fig.transFigure, ax.transAxes))
    gap_px = (axes[0].yaxis.labelpad * dpi / 72.0) if label_w else 0.0
    for _ in range(3):
        lefts = []
        for ax in axes:
            boxes = [t.get_window_extent(renderer) for t in ax.get_yticklabels()
                     if t.get_visible() and t.get_text()]
            if boxes:
                lefts.append(min(b.x0 for b in boxes))
        if not lefts:
            break
        shift = (label_right_px + gap_px - min(lefts)) / fig_w_px
        if abs(shift) * fig_w_px < 0.25:
            break
        for ax in axes:
            pos = ax.get_position()
            x0 = pos.x0 + shift
            ax.set_position([x0, pos.y0, right - x0, pos.height])
    for ax in axes:
        pos = ax.get_position()
        ax.set_position([pos.x0, pos.y0, right - pos.x0, pos.height])


PEAK_COLS = [
    _Col("#", 0.35, "right", lambda v: f"{v}"),
    _Col("Name", 1.28),
    _Col("RT (min)", 0.72, "right", lambda v: f"{v:.3f}"),
    _Col("Area (µV·s)", 1.25, "right", lambda v: f"{v:,.2f}"),
    _Col("Height (µV)", 1.1, "right", lambda v: f"{v:,.2f}"),
    _Col("Area %", 0.68, "right", lambda v: f"{v:.2f}"),
    _Col("Baseline", 0.62),
    _Col("Flags", 1.3),
]


def _scaled(cols: list[_Col], width: float) -> list[_Col]:
    """Columns resized proportionally to fill ``width`` (inches)."""
    f = width / sum(c.width for c in cols)
    return [_Col(c.header, c.width * f, c.align, c.fmt) for c in cols]


def _run_notes(entry: ReportEntry, options: ReportOptions) -> list[tuple[str, dict]]:
    run, res = entry.run, entry.result
    bold, grey = {"fontweight": "bold"}, {"color": "0.3"}
    lines: list[tuple[str, dict]] = [
        (f"Total area {res.total_area_uv_s:,.2f} µV·s in {len(res.peaks)} "
         f"peak{'s' if len(res.peaks) != 1 else ''}.", bold)]
    if any(p.clipped for p in res.peaks):
        lines.append((CLIPPING_WARNING, grey))
    if any("baseline-penetration" in p.flags for p in res.peaks):
        lines.append(("baseline-penetration: the signal dips below a drawn baseline.", grey))
    if entry.missing:
        lines.append(("Components not found: " + ", ".join(entry.missing) + ".", grey))
    seen = {text for text, _ in lines}
    for w in (*run.warnings, *res.warnings):
        if w not in seen:
            lines.append(("Warning: " + w, grey))
            seen.add(w)
    for n in (*options.notes, *entry.notes):
        lines.append((n, grey))
    return [("", {})] + lines


MIN_MAIN_PLOT = 2.6
MAX_MAIN_PLOT = 6.0


def _run_section(entry: ReportEntry, options: ReportOptions, size: tuple[float, float]):
    usable_w = size[0] - 2 * MARGIN_X
    header = _run_header(entry, usable_w, options)
    strip_h = 1.25 if options.full_scale_strip else 0.0
    main_h = 3.35 if options.full_scale_strip else 4.2
    rows = [[p.number, entry.names.get(p.number, ""), p.rt_min, p.area_uv_s, p.height_uv,
             p.area_pct, p.baseline_code, " ".join(p.flags)] for p in entry.result.peaks]
    notes = [(line, style) for text, style in _run_notes(entry, options)
             for line in (textwrap.wrap(text, max(20, int(usable_w * CHARS_PER_INCH))) or [""])]
    page_h = size[1] - MARGIN_BOTTOM - MARGIN_TOP - RUNNING_HEADER
    if options.peak_table_new_page:
        main_h = min(MAX_MAIN_PLOT, page_h - header.height - strip_h - 0.01)
    else:
        rest = header.height + strip_h + (LINE_H + 0.03) + HEAD_H + ROW_H * max(len(rows), 1) \
            + 0.18 + LINE_H * len(notes)
        if rest + main_h > page_h and rest + MIN_MAIN_PLOT <= page_h:
            main_h = page_h - rest - 0.01
    items: list = [header]
    if options.full_scale_strip:
        items.append(_plot_block(entry, usable_w, strip_h, options, strip=True))
    items.append(_plot_block(entry, usable_w, main_h, options, strip=False))
    if options.peak_table_new_page:
        items.append(_Break())
    items.append(_Table(_scaled(PEAK_COLS, usable_w), rows, title="Peaks",
                        empty_text="No peaks detected."))
    items.append(_Lines(notes))
    return _run_label(entry), items


def _summary_section(entries: Sequence[ReportEntry], size: tuple[float, float]):
    usable_w = size[0] - 2 * MARGIN_X
    comps: list[str] = []
    for e in entries:
        for p in e.result.peaks:
            n = e.names.get(p.number)
            if n and n not in comps:
                comps.append(n)
    for e in entries:
        for n in e.missing:
            if n not in comps:
                comps.append(n)
    settings = {_settings_text(e.result) + "; timed events: " + _events_text(e.result)
                for e in entries}
    base = [_Col("#", 0.3, "right"), _Col("File", 1.55), _Col("Sample", 1.0),
            _Col("Injected", 1.2), _Col("Peaks", 0.5, "right")]
    free = usable_w - sum(c.width for c in base)

    def base_row(i: int, e: ReportEntry) -> list:
        return [i + 1, e.run.path.name if e.run.path else "", e.run.header.sample_name,
                _local(e.run.header.injection_utc, "%Y-%m-%d %H:%M"), len(e.result.peaks)]

    tables = []
    if comps:
        per = max(1, int(free // 0.9))
        for k in range(0, len(comps), per):
            chunk = comps[k:k + per]
            cols = base + [_Col(c, free / len(chunk), "right", lambda v: f"{v:,.2f}") for c in chunk]
            rows = []
            for i, e in enumerate(entries):
                area = {e.names.get(p.number): p.area_uv_s for p in e.result.peaks}
                rows.append(base_row(i, e) + [area.get(c) for c in chunk])
            title = "Component areas (µV·s)" + (f", part {k // per + 1}" if len(comps) > per else "")
            tables.append(_Table(cols, rows, title=title))
    else:
        cols = base + [_Col("Total area (µV·s)", free - 0.9, "right", lambda v: f"{v:,.2f}"),
                       _Col("Clipped", 0.9, "right")]
        rows = [base_row(i, e) + [e.result.total_area_uv_s, sum(p.clipped for p in e.result.peaks)]
                for i, e in enumerate(entries)]
        tables.append(_Table(cols, rows, title="Runs"))

    def draw(page: _Page, y: float) -> None:
        page.text(MARGIN_X, y, f"Summary of {len(entries)} runs", fontsize=13, fontweight="bold")
        info = [("Integration", next(iter(settings)) if len(settings) == 1
                 else "differs between runs; see each run's page"),
                ("Components", ", ".join(comps) if comps else "none named")]
        for i, (label, value) in enumerate(info):
            page.text(MARGIN_X, y + 0.34 + i * LINE_H, label, color="0.35")
            page.text(MARGIN_X + 1.05, y + 0.34 + i * LINE_H, _fit_middle(value, usable_w - 1.15))
        page.hline(y + 0.34 + len(info) * LINE_H + 0.07)

    header = _Fixed(0.34 + 2 * LINE_H + 0.2, draw)
    return "Summary", [header, *tables]


def write_report(path: str | Path, entries: ReportEntry | Sequence[ReportEntry],
                 options: ReportOptions = ReportOptions()) -> ReportInfo:
    if isinstance(entries, ReportEntry):
        entries = [entries]
    entries = list(entries)
    if not entries:
        raise ValueError("nothing to report")
    size = PAGE_SIZES[options.page_size.lower()]
    sections = [] if len(entries) == 1 else [_summary_section(entries, size)]
    sections += [_run_section(e, options, size) for e in entries]
    pages = _paginate(sections, size)
    generated = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    path = Path(path)
    meta = {"Title": options.title, "Creator": f"tcfid {TOTALCHROM_VERSION}",
            "Subject": f"{len(entries)} run{'s' if len(entries) != 1 else ''}",
            "Keywords": "chromatography; GC-FID; TotalChrom"}
    with matplotlib.rc_context(RC), PdfPages(path, metadata=meta) as pdf:
        for i, spec in enumerate(pages):
            page = _Page(size)
            page.text(MARGIN_X, MARGIN_TOP, options.title, fontsize=9, fontweight="bold")
            if options.subtitle:
                page.text(MARGIN_X, MARGIN_TOP + 0.17, options.subtitle, fontsize=7.5, color="0.35")
            context = _fit_middle(spec["context"], 3.6)
            page.text(page.w - MARGIN_X, MARGIN_TOP, context,
                      fontsize=8, ha="right", color="0.3")
            page.hline(MARGIN_TOP + RUNNING_HEADER - 0.08, color="0.4", lw=0.8)
            for kind, y, payload in spec["ops"]:
                if kind == "fixed":
                    payload.draw(page, y)
                elif kind == "line":
                    text, style = payload
                    if text:
                        page.text(MARGIN_X, y, _fit(text, page.w - 2 * MARGIN_X), **style)
                else:
                    table, rows, title = payload
                    _draw_table(page, MARGIN_X, y, table, rows, title)
            fy = page.h - MARGIN_BOTTOM + 0.3
            page.text(MARGIN_X, fy, f"Generated {generated}", fontsize=6.5, color="0.5")
            page.text(page.w - MARGIN_X, fy, f"Page {i + 1} of {len(pages)}",
                      fontsize=6.5, color="0.5", ha="right")
            if options.disclaimer:
                page.text(MARGIN_X, fy + 0.15, options.disclaimer, fontsize=6.5, color="0.5")
            _align_plot_axes(page)
            pdf.savefig(page.fig)
    return ReportInfo(path, len(pages))

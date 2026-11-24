"""UI-independent source traces, presentation state and report rendering.

No pyplot/backend selection or global rcParams changes. Display ranges never
modify source arrays. Label anchors are sample indices; text uses axes fractions.
"""
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
import hashlib
import json
import math
import os
import tempfile

import numpy as np
from gcviewer.figures.styles import FIGURE_STYLES
from gcviewer.analysis.processing import display_signal, processing_metadata, signal_axis_label, validate_processing


from gcviewer.data_models.acquisition import Trace


@dataclass
class FigureSettings:
    title: str = ""
    x_label: str = "Retention time (min)"
    y_label: str = "Signal (a.u.)"
    width_mm: float = 180
    height_mm: float = 110
    font_size: float = 10
    auto_font_size: bool = True
    font_family: str = "Arial"
    publication_style: str = "general"
    line_width: float = 1
    color: str = "#20252b"
    dpi: int = 300
    x_range: tuple[float, float] | None = None
    y_range: tuple[float, float] | None = None
    x_break: tuple[float, float] | None = None
    y_break: tuple[float, float] | None = None
    y_numbers: str = "readable"
    comparison_mode: str = "overlay"
    trace_colors: tuple[str, ...] = ()
    trace_names: tuple[str, ...] = ()
    smoothing_window: int = 1
    normalize: bool = False

    def validate(self, trace):
        for item in source_traces(trace):
            validate_processing(item, self)
        if self.publication_style not in FIGURE_STYLES:
            raise ValueError("Choose a supported figure style.")
        if self.font_family not in ("Arial", "Helvetica", "DejaVu Sans", "Times New Roman"):
            raise ValueError("Choose a supported figure font.")
        if self.y_numbers not in ("readable", "scientific", "plain"):
            raise ValueError("Choose readable, scientific or full axis numbers.")
        for name, lo, hi in (("width_mm", 80, 300), ("height_mm", 40, 250),
                             ("font_size", 6, 24), ("line_width", .2, 5), ("dpi", 72, 1200)):
            value = getattr(self, name)
            if not math.isfinite(value) or not lo <= value <= hi:
                raise ValueError(f"{name.replace('_', ' ')} must be between {lo} and {hi}.")
        for label, limits in ((trace.x_label, self.x_range), ("Signal", self.y_range)):
            if limits is not None and (len(limits) != 2 or
                    not all(math.isfinite(v) for v in limits) or limits[0] >= limits[1]):
                raise ValueError(f"{label} range needs two finite values with minimum < maximum.")
        if self.x_range and not any(np.any((item.time >= self.x_range[0]) & (item.time <= self.x_range[1])) for item in source_traces(trace)):
            raise ValueError("The X range contains no data points. Widen it or use Auto.")
        if is_comparison(trace):
            trace.validate_settings(self)
        from gcviewer.figures.axis_breaks import validate_breaks
        validate_breaks(trace, self)
        from matplotlib.colors import is_color_like
        if not is_color_like(self.color):
            raise ValueError("Choose a valid trace color.")


@dataclass
class PeakLabel:
    index: int
    text: str
    position: tuple[float, float] = (.5, .8)
    trace_index: int = 0
    visible: bool = True
    origin: str = "manual"
    generation: dict = field(default_factory=dict)


@dataclass
class FigureState:
    settings: FigureSettings
    labels: list[PeakLabel] = field(default_factory=list)

    @classmethod
    def report(cls, trace):
        settings = FigureSettings(title=trace.name, x_label=trace.x_label, y_label=trace.y_label)
        if is_comparison(trace):
            from gcviewer.figures.comparisons import COLORS
            settings.trace_colors = tuple(COLORS[i % len(COLORS)] for i in range(len(trace.traces)))
            settings.trace_names = tuple(f"{i + 1}. {t.name}" + (f" / {t.function}" if t.function else "") for i, t in enumerate(trace.traces))
        return cls(settings)

    def add_label(self, trace, time, text=None, position=None, trace_index=0):
        trace = source_traces(trace)[trace_index]
        index = int(np.argmin(np.abs(trace.time - time)))
        if position is None:
            limits = self.settings.x_range or (trace.time[0], trace.time[-1])
            span = limits[1] - limits[0]
            position = (float(np.clip((trace.time[index] - limits[0]) / span, .1, .9)) if span else .5, .8)
        text = text or (f"m/z {trace.time[index]:g}" if trace.x_unit == "m/z" else f"{trace.time[index]:.2f} {trace.x_unit}")
        label = PeakLabel(index, text, position, trace_index)
        self.labels.append(label)
        return label


def is_comparison(trace):
    from gcviewer.figures.comparisons import Comparison
    return isinstance(trace, Comparison)


def source_traces(trace):
    """Ordered immutable input traces; a comparison never fabricates merged data."""
    return trace.traces if is_comparison(trace) else (trace,)


def demo_trace():
    time = np.linspace(0, 12, 6001)
    signal = 6 + .4 * time + .7 * np.sin(time * 11)
    for center, width, height in ((1.65, .11, 34), (3.1, .16, 66), (5.05, .09, 85),
                                  (5.3, .085, 73), (5.53, .1, 94), (8.1, .22, 51), (10.25, .12, 27)):
        signal += height * np.exp(-.5 * ((time - center) / width)**2)
    return Trace("Synthetic demo — crowded peaks", "synthetic://crowded-peaks-v1", "Synthetic",
                 time, signal, y_label="Synthetic signal (a.u.)", synthetic=True,
                 metadata={"generator": "crowded-peaks-v1", "points": len(time)},
                 warnings=("Synthetic example; no experimental acquisition or compound identification.",))


def y_axis_display(trace, settings):
    """Tick formatting; curves and anchors use explicitly processed values."""
    if (trace.instrument == "GC-FID" and trace.y_label == "Response (µV)"
            and settings.y_label == trace.y_label and not settings.normalize and settings.y_numbers == "readable"):
        return {"mode": "readable", "divisor": 1000., "label": "Response (mV)"}
    signals = [display_signal(t, settings) for t in source_traces(trace)]
    maximum = max(abs(v) for v in (settings.y_range or tuple(v for signal in signals for v in (float(signal.min()), float(signal.max())))))
    divisor, unit = 1., ""
    if settings.y_numbers == "readable" and maximum and not settings.normalize:
        for threshold, label in ((1e12, "trillions"), (1e9, "billions"), (1e6, "millions"), (1e3, "thousands")):
            if maximum >= threshold:
                divisor, unit = threshold, label
                break
    separator = "\n" if settings.height_mm < 80 else " — "
    label = signal_axis_label(trace, settings) + (f"{separator}{unit}" if unit else "")
    return {"mode": settings.y_numbers,
            "divisor": None if settings.y_numbers == "scientific" else divisor,
            "label": label}


@lru_cache(maxsize=8)
def resolved_font(family):
    """Use installed fonts; the bundled DejaVu fallback remains explicit."""
    from matplotlib.font_manager import FontProperties, findfont
    try:
        path = findfont(FontProperties(family=family), fallback_to_default=False)
    except ValueError:
        return "DejaVu Sans"
    return FontProperties(fname=path).get_name()


def figure_typography(settings):
    size = settings.font_size
    if settings.auto_font_size:
        size = FIGURE_STYLES[settings.publication_style].text_pt
        if size is None:
            size = round(max(7, min(10, 10 * math.sqrt(min(settings.width_mm / 180,
                                                         settings.height_mm / 110)))), 1)
    return {"font_family": resolved_font(settings.font_family),
            "requested_font_family": settings.font_family, "font_size_pt": size,
            "automatic": settings.auto_font_size}


def render_figure(trace, state, figure=None):
    """The only renderer for the preview and every export format."""
    if is_comparison(trace):
        from gcviewer.figures.comparisons import render_comparison
        return render_comparison(trace, state, figure)
    s = state.settings
    s.validate(trace)
    from matplotlib.figure import Figure
    from gcviewer.figures.axis_breaks import make_panels, style_ticks, display_path
    fig = figure if figure is not None else Figure()
    fig.clear()
    fig.set_size_inches(s.width_mm / 25.4, s.height_mm / 25.4, forward=False)
    fig.set_facecolor("white")
    typography = figure_typography(s)
    font, family = typography["font_size_pt"], typography["font_family"]
    text_scale = font / 10
    left = max(.11, 18 * text_scale / s.width_mm)
    bottom = max(.14, (16 if trace.synthetic else 12) * text_scale / s.height_mm)
    top = max(.12, 10 * text_scale / s.height_mm)
    ax = fig.add_axes((left, bottom, .96 - left, 1 - bottom - top))
    signal = display_signal(trace, s)
    ax.plot(*display_path(trace, settings=s), color=s.color, linewidth=s.line_width)
    ax.set_title(s.title, fontsize=font, fontfamily=family, pad=10 * text_scale)
    ax.set_xlabel(s.x_label, fontsize=font, fontfamily=family, labelpad=4 * text_scale)
    display = y_axis_display(trace, s)
    ax.set_ylabel(display["label"], fontsize=font, fontfamily=family, labelpad=4 * text_scale)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_linewidth(.6)
    ax.margins(x=.01, y=.17)
    if s.x_range is not None:
        ax.set_xlim(*s.x_range)
    if s.y_range is not None:
        ax.set_ylim(*s.y_range)
    elif np.min(signal) >= 0:
        maximum = float(np.max(signal))
        ax.set_ylim(0, maximum * 1.17 if maximum else 1.)
    panels, label_transform = make_panels(fig, ax, trace, s, font)
    for panel in panels:
        style_ticks(panel, trace, s, display, font, family)
    fig.report_panels = panels
    fig.report_label_transform = label_transform
    artists = []
    for label in state.labels:
        if not label.visible:
            artists.append(None)
            continue
        if not 0 <= label.index < len(trace.time):
            raise ValueError("A label anchor is outside this trace.")
        xy = (trace.time[label.index], signal[label.index])
        anchor_ax = next((panel for panel in panels if
                         panel.get_xlim()[0] <= xy[0] <= panel.get_xlim()[1] and
                         panel.get_ylim()[0] <= xy[1] <= panel.get_ylim()[1]), None)
        if anchor_ax is None and (s.x_break or s.y_break):
            artists.append(None)
            continue
        artist = (anchor_ax or ax).annotate(label.text, xy=xy,
                             xytext=label.position, textcoords=label_transform,
                             fontsize=font, fontfamily=family, ha="center", va="center",
                             arrowprops={"arrowstyle": "-", "color": "#666666", "lw": .65},
                             bbox={"boxstyle": "round,pad=0.2", "fc": "white", "ec": "none", "alpha": .92},
                             annotation_clip=True)
        artist.set_zorder(11 - label.position[1])
        if s.x_break or s.y_break:
            artist.remove()
            artist.axes = anchor_ax
            artist.set_zorder(11 - label.position[1])
            fig.add_artist(artist)
        artists.append(artist)
    if trace.synthetic:
        fig.text(left, .035, "SYNTHETIC DEMO · not experimental data",
                 fontsize=max(6, font * .75), color="#555555", fontfamily=family)
    return fig, ax, artists


def export_paths(path, trace, *, extensions=(".png", ".pdf", ".svg", ".tif", ".tiff")):
    path = Path(path).expanduser().resolve()
    if path.suffix.lower() not in extensions:
        raise ValueError("Choose a filename ending in " + ", ".join(extensions) + ".")
    sidecar = path.with_suffix(path.suffix + ".json")
    if any(p.suffix.lower() == ".raw" for p in path.parents):
        raise ValueError("Save figures outside acquisition .raw directories.")
    for item in source_traces(trace):
        if not item.synthetic:
            source = Path(item.source).resolve()
            if path == source or sidecar == source or source in path.parents:
                raise ValueError("Acquisition inputs cannot be overwritten.")
    return path, sidecar


def export_figure(trace, state, path, *, overwrite=False):
    path, sidecar = export_paths(path, trace)
    state.settings.validate(trace)
    if path.suffix.lower() in (".png", ".tif", ".tiff"):
        s = state.settings
        if s.width_mm * s.height_mm / 25.4**2 * s.dpi**2 > 24_000_000:
            raise ValueError("This raster export exceeds 24 megapixels. Use vector PDF/SVG, a smaller figure, or lower DPI.")
    if not overwrite and (path.exists() or sidecar.exists()):
        raise FileExistsError("The figure or metadata sidecar already exists.")
    fig, _, artists = render_figure(trace, state)
    metadata = figure_metadata(trace, state, artists)
    return write_figure(fig, state.settings, path, sidecar, metadata, overwrite=overwrite)


def figure_metadata(trace, state, artists):
    if is_comparison(trace):
        from gcviewer.figures.comparisons import comparison_metadata
        return comparison_metadata(trace, state)
    checksum = hashlib.sha256(trace.time.astype("<f8").tobytes() + trace.signal.astype("<f8").tobytes()).hexdigest()
    signal = display_signal(trace, state.settings)
    return {
        "schema": "chromatogram-figure-v1", "source": trace.source, "sample": trace.name,
        "instrument": trace.instrument, "function": trace.function, "synthetic": trace.synthetic,
        "source_metadata": trace.metadata, "transformations": list(trace.transformations),
        "warnings": list(trace.warnings), "point_count": len(trace.time), "trace_sha256": checksum,
        "x_quantity": trace.x_label, "x_unit": trace.x_unit, "plot_kind": trace.plot_kind,
        "settings": asdict(state.settings), "annotations": [dict(asdict(label),
            **({"anchor_time_min": float(trace.time[label.index])} if trace.x_unit == "min" else {"anchor_mz": float(trace.time[label.index])}),
            anchor_signal=float(trace.signal[label.index]),
            displayed_anchor_signal=float(signal[label.index]),
            hidden_by_axis_break=bool(
                (state.settings.x_break and state.settings.x_break[0] < trace.time[label.index] < state.settings.x_break[1]) or
                (state.settings.y_break and state.settings.y_break[0] < signal[label.index] < state.settings.y_break[1])))
            for label, artist in zip(state.labels, artists)],
        "display_only": "Axis ranges and breaks hide parts of the processed view; source arrays are unchanged. Processing is explicitly recorded below.",
        "processing": processing_metadata(trace, state.settings),
        "axis_breaks": {"x_omitted": state.settings.x_break, "y_omitted": state.settings.y_break,
                        "units": f"{trace.x_label} and displayed signal units, after processing and before tick-label scaling.",
                        "retained_scale": "Linear; equal units per physical length on either side of each break."},
        "y_axis_display": y_axis_display(trace, state.settings),
        "typography": figure_typography(state.settings),
        "publication_guidance": {"preset": state.settings.publication_style,
                                 "source_url": FIGURE_STYLES[state.settings.publication_style].source_url,
                                 "note": "Starting defaults; custom settings and the target journal's current requirements must be checked."},
    }


def write_figure(fig, settings, path, sidecar, metadata, *, overwrite=False):
    temporary = []
    try:
        for suffix in (path.suffix, ".json"):
            fd, name = tempfile.mkstemp(prefix=".figure-", suffix=suffix, dir=path.parent)
            os.close(fd)
            temporary.append(Path(name))
        from matplotlib import rc_context
        with rc_context({"pdf.fonttype": 42, "svg.fonttype": "none"}):
            fmt = path.suffix[1:].lower()
            kwargs = {"pil_kwargs": {"compression": "tiff_lzw"}} if fmt in ("tif", "tiff") else {}
            fig.savefig(temporary[0], format=fmt, dpi=settings.dpi,
                        facecolor="white", bbox_inches=None, **kwargs)
        temporary[1].write_text(json.dumps(metadata, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        if not overwrite and (path.exists() or sidecar.exists()):
            raise FileExistsError("The figure or metadata sidecar already exists.")
        os.replace(temporary[0], path)
        os.replace(temporary[1], sidecar)
    finally:
        for staged in temporary:
            staged.unlink(missing_ok=True)
    return path, sidecar

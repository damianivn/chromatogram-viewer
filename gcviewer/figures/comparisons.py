"""Ordered chromatogram comparisons with original, independently sampled data."""
from dataclasses import asdict, dataclass, replace
import hashlib
import textwrap


from gcviewer.data_models.acquisition import Trace
from gcviewer.figures.workspace import figure_typography, y_axis_display
from gcviewer.analysis.processing import display_signal, processing_metadata


COLORS = ("#4477aa", "#ee6677", "#228833", "#aa3377", "#66ccee", "#ccbb44", "#20252b")


class ComparisonLayoutError(ValueError):
    """The requested lettering/panels need a taller physical figure."""


@dataclass(frozen=True)
class Comparison:
    traces: tuple[Trace, ...]
    name: str = "Chromatogram comparison"

    def __post_init__(self):
        object.__setattr__(self, "traces", tuple(self.traces))
        if len(self.traces) < 2:
            raise ValueError("Choose at least two loaded chromatograms.")
        if any(not isinstance(t, Trace) or t.plot_kind != "line" or t.x_unit != "min" for t in self.traces):
            raise ValueError("Choose chromatograms, rather than spectra or existing comparisons.")
        first = self.traces[0]
        if any((t.instrument, t.x_unit, t.y_label, t.synthetic) !=
               (first.instrument, first.x_unit, first.y_label, first.synthetic) for t in self.traces):
            raise ValueError("Compare samples from the same instrument with matching signal units. Keep synthetic examples separate.")

    @property
    def instrument(self):
        return self.traces[0].instrument

    @property
    def x_label(self):
        return self.traces[0].x_label

    @property
    def y_label(self):
        return self.traces[0].y_label

    x_unit = "min"
    plot_kind = "comparison"
    function = ""
    transformations = ()

    @property
    def synthetic(self):
        return self.traces[0].synthetic

    @property
    def source(self):
        return "\n".join(f"{i + 1}. {t.source}" for i, t in enumerate(self.traces))

    @property
    def warnings(self):
        return tuple(dict.fromkeys(w for t in self.traces for w in t.warnings))

    @property
    def metadata(self):
        return {}

    def validate_settings(self, settings):
        from matplotlib.colors import is_color_like
        if settings.comparison_mode not in ("overlay", "stacked"):
            raise ValueError("Choose Overlay or Stacked.")
        if len(settings.trace_colors) != len(self.traces) or not all(is_color_like(c) for c in settings.trace_colors):
            raise ValueError("Each comparison trace needs a valid color.")
        if len(settings.trace_names) != len(self.traces) or not all(n.strip() for n in settings.trace_names):
            raise ValueError("Each comparison trace needs a label.")
        layout = comparison_layout(self, settings)
        if layout["plot_height"] < (18 if settings.comparison_mode == "stacked" else 22):
            raise ComparisonLayoutError("This comparison needs more figure height for its labels and traces. Increase Height, shorten labels, or choose fewer samples.")


def fitted_settings(comparison, settings):
    """Fit creation/mode/reset defaults; explicit size edits remain exact."""
    settings = replace(settings)
    while True:
        try:
            settings.validate(comparison)
            return settings
        except ComparisonLayoutError:
            if settings.height_mm >= 250:
                raise
            settings.height_mm += min(10, 250 - settings.height_mm)


def comparison_layout(comparison, settings):
    font = figure_typography(settings)["font_size_pt"]
    line_mm = font * 1.3 * 25.4 / 72
    columns = 2 if settings.width_mm >= 140 and settings.comparison_mode == "overlay" else 1
    chars = max(12, int((settings.width_mm - 30) / columns * 72 / 25.4 / (font * .6)))
    names = [textwrap.fill(n, chars) for n in settings.trace_names]
    bottom, top = max(12, font * 1.3), max(10, font * 1.1)
    if comparison.synthetic:
        bottom += 4
    if settings.comparison_mode == "overlay":
        rows = (len(names) + columns - 1) // columns
        legend_lines = sum(max(names[j].count("\n") + 1 for j in range(i, len(names), rows)) for i in range(rows))
        legend_height = legend_lines * line_mm + rows * 1.1 + 3
        plot_height = settings.height_mm - bottom - top - legend_height
        headers = []
    else:
        legend_height = 0
        headers = [(n.count("\n") + 1) * line_mm + 2 for n in names]
        plot_height = (settings.height_mm - bottom - top - sum(headers) - 3 * (len(names) - 1)) / len(names)
    return dict(names=names, columns=columns, top=top, bottom=bottom,
                legend_height=legend_height, headers=headers, plot_height=plot_height)


def render_comparison(comparison, state, figure=None):
    from matplotlib.figure import Figure
    from matplotlib.lines import Line2D
    from matplotlib.ticker import MaxNLocator
    from matplotlib.transforms import Bbox, BboxTransformTo
    from gcviewer.figures.axis_breaks import display_path, make_panels, style_ticks, view_limits

    s = state.settings
    s.validate(comparison)
    fig = figure if figure is not None else Figure()
    fig.clear()
    fig.set_size_inches(s.width_mm / 25.4, s.height_mm / 25.4, forward=False)
    fig.set_facecolor("white")
    typography = figure_typography(s)
    font, family = typography["font_size_pt"], typography["font_family"]
    layout = comparison_layout(comparison, s)
    left, right = max(.11, 18 * font / 10 / s.width_mm), .96
    bottom, top = layout["bottom"] / s.height_mm, 1 - layout["top"] / s.height_mm
    fig.text((left + right) / 2, 1 - 2 / s.height_mm, s.title,
             ha="center", va="top", fontsize=font, fontfamily=family)
    transform = BboxTransformTo(Bbox.from_extents(left, bottom, right, top)) + fig.transFigure
    fig.report_label_transform = transform
    xlim, ylim = view_limits(comparison, s)
    display = y_axis_display(comparison, s)
    panels = []
    groups = [(comparison, tuple(zip(comparison.traces, s.trace_colors)))] if s.comparison_mode == "overlay" else [
        (trace, ((trace, color),)) for trace, color in zip(comparison.traces, s.trace_colors)]
    cursor = top
    for index, (data, series) in enumerate(groups):
        if s.comparison_mode == "overlay":
            cursor -= layout["legend_height"] / s.height_mm
        else:
            fig.text(left, cursor, layout["names"][index], va="top", ha="left",
                     fontsize=font, fontfamily=family, color=s.trace_colors[index])
            cursor -= layout["headers"][index] / s.height_mm
        height = layout["plot_height"] / s.height_mm
        ax = fig.add_axes((left, cursor - height, right - left, height))
        for trace, color in series:
            ax.plot(*display_path(trace, settings=s), color=color, linewidth=s.line_width)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_linewidth(.6)
        panel_settings = replace(s, x_range=xlim, y_range=ylim, title="", color=series[0][1])
        group, _ = make_panels(fig, ax, data, panel_settings, font, series=series)
        for panel in group:
            panel.report_trace_index = None if s.comparison_mode == "overlay" else index
            style_ticks(panel, comparison, panel_settings, display, font, family)
            if not s.y_break:
                panel.yaxis.set_major_locator(MaxNLocator(nbins=max(3, int(layout["plot_height"] / 12)), min_n_ticks=3))
            if index < len(groups) - 1:
                panel.tick_params(bottom=False, labelbottom=False)
                panel.spines["bottom"].set_visible(False)
                for line in panel.lines:
                    if line.get_gid() == "x-axis-break":
                        line.set_visible(False)
            panels.append(panel)
        cursor -= height + 3 / s.height_mm
    fig.report_panels = panels
    fig.text((left + right) / 2, bottom - 9 * font / 10 / s.height_mm, s.x_label,
             ha="center", va="top", fontsize=font, fontfamily=family)
    fig.text(max(.014, left - 13 * font / 10 / s.width_mm), (bottom + top - layout["legend_height"] / s.height_mm) / 2,
             display["label"], rotation=90, ha="center", va="center", fontsize=font, fontfamily=family)
    if s.comparison_mode == "overlay":
        handles = [Line2D([], [], color=c, linewidth=s.line_width) for c in s.trace_colors]
        fig.legend(handles, layout["names"], loc="upper left", bbox_to_anchor=(left, top),
                   bbox_transform=fig.transFigure, frameon=False, borderaxespad=0, borderpad=0,
                   ncol=layout["columns"], handlelength=1.6, columnspacing=1.2,
                   prop={"family": family, "size": font})
    artists = []
    for label in state.labels:
        if not label.visible:
            artists.append(None)
            continue
        if not 0 <= label.trace_index < len(comparison.traces):
            raise ValueError("A label belongs to an unavailable comparison trace.")
        trace = comparison.traces[label.trace_index]
        if not 0 <= label.index < len(trace.time):
            raise ValueError("A label anchor is outside this trace.")
        x, y = trace.time[label.index], display_signal(trace, s)[label.index]
        anchor = next((p for p in panels if p.report_trace_index in (None, label.trace_index)
                       and p.get_xlim()[0] <= x <= p.get_xlim()[1] and p.get_ylim()[0] <= y <= p.get_ylim()[1]), None)
        if anchor is None:
            artists.append(None)
            continue
        artist = anchor.annotate(label.text, (x, y), xytext=label.position, textcoords=transform,
                                 fontsize=font, fontfamily=family, ha="center", va="center",
                                 arrowprops={"arrowstyle": "-", "color": s.trace_colors[label.trace_index], "lw": .65},
                                 bbox={"boxstyle": "round,pad=0.2", "fc": "white", "ec": "none", "alpha": .92})
        artist.remove()
        artist.axes = anchor
        artist.set_zorder(11 - label.position[1])
        fig.add_artist(artist)
        artists.append(artist)
    if comparison.synthetic:
        fig.text(left, .015, "SYNTHETIC DEMO · not experimental data", fontsize=max(6, font * .75), fontfamily=family, color="#555555")
    return fig, panels[0], artists


def trace_record(trace, index):
    return {"trace_id": index + 1, "source": trace.source, "sample": trace.name, "instrument": trace.instrument,
            "function": trace.function, "synthetic": trace.synthetic, "source_metadata": trace.metadata,
            "transformations": list(trace.transformations), "warnings": list(trace.warnings),
            "x_quantity": trace.x_label, "x_unit": trace.x_unit, "signal_quantity": trace.y_label,
            "point_count": len(trace.time), "trace_sha256": hashlib.sha256(
                trace.time.astype("<f8").tobytes() + trace.signal.astype("<f8").tobytes()).hexdigest()}


def comparison_metadata(comparison, state):
    from gcviewer.figures.styles import FIGURE_STYLES
    s = state.settings
    annotations = []
    for label in state.labels:
        trace = comparison.traces[label.trace_index]
        x, y = float(trace.time[label.index]), float(display_signal(trace, s)[label.index])
        annotations.append(dict(asdict(label), trace_id=label.trace_index + 1, anchor_time_min=x,
                                anchor_signal=float(trace.signal[label.index]), displayed_anchor_signal=y,
                                hidden_by_axis_break=bool((s.x_break and s.x_break[0] < x < s.x_break[1]) or
                                                          (s.y_break and s.y_break[0] < y < s.y_break[1]))))
    return {"schema": "chromatogram-comparison-figure-v1", "mode": s.comparison_mode,
            "traces": [dict(trace_record(t, i), label=s.trace_names[i], color=s.trace_colors[i]) for i, t in enumerate(comparison.traces)],
            "settings": asdict(s), "annotations": annotations, "typography": figure_typography(s),
            "y_axis_display": y_axis_display(comparison, s),
            "display_only": "Shared linear time and displayed signal scales. Original time grids; no alignment or resampling. Explicit processing precedes figure ranges and breaks; source arrays are unchanged.",
            "processing": processing_metadata(comparison, s),
            "publication_guidance": {"preset": s.publication_style, "source_url": FIGURE_STYLES[s.publication_style].source_url}}

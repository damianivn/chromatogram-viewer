"""Presentation-only axis breaks. No Qt or parser dependencies.

Each retained interval is a real linear Matplotlib axis. Display paths are
clipped at panel edges, never joined across an omitted interval. Text positions
refer to the complete plot rectangle, independent of the number of panels.
"""
import math
import numpy as np
from gcviewer.analysis.processing import display_signal


def view_limits(trace, settings):
    from gcviewer.figures.workspace import source_traces
    traces = source_traces(trace)
    x = settings.x_range
    if x is None:
        lo, hi = min(float(t.time[0]) for t in traces), max(float(t.time[-1]) for t in traces)
        pad = (hi - lo) * .01 if hi > lo else max(abs(lo) * .01, .5)
        x = (lo - pad, hi + pad)
    y = settings.y_range
    if y is None:
        signals = [display_signal(t, settings) for t in traces]
        lo, hi = min(float(np.min(y)) for y in signals), max(float(np.max(y)) for y in signals)
        if lo >= 0:
            y = (0., hi * 1.17 if hi else 1.)
        else:
            from matplotlib.ticker import Locator
            lo, hi = Locator().nonsingular(lo, hi)
            pad = (hi - lo) * .17
            y = (lo - pad, hi + pad)
    return tuple(x), tuple(y)


def intervals(limits, omitted):
    return [(limits[0], omitted[0]), (omitted[1], limits[1])] if omitted else [limits]


def clipped_path(time, signal, xlim, ylim):
    """Clip line segments, including boundary intersections, for SVG portability.

    Some SVG viewers ignore rectangular clip paths. Emit only the visible line
    geometry and use NaN separators for excursions outside the panel. The
    original samples are untouched; intersection points are display-only.
    """
    start = max(0, int(np.searchsorted(time, xlim[0])) - 1)
    stop = min(len(time), int(np.searchsorted(time, xlim[1], side="right")) + 1)
    points = np.column_stack((time[start:stop], signal[start:stop]))
    first, delta = points[:-1], np.diff(points, axis=0)
    if not len(first):
        return np.array([]), np.array([])
    lower, upper = np.array((xlim[0], ylim[0])), np.array((xlim[1], ylim[1]))
    moving = delta != 0
    a = np.divide(lower - first, delta, out=np.full_like(first, -np.inf), where=moving)
    b = np.divide(upper - first, delta, out=np.full_like(first, np.inf), where=moving)
    lo = np.maximum(0, np.minimum(a, b).max(axis=1))
    hi = np.minimum(1, np.maximum(a, b).min(axis=1))
    stationary_outside = ((~moving) & ((first < lower) | (first > upper))).any(axis=1)
    indices = np.flatnonzero((lo <= hi) & ~stationary_outside)
    if not len(indices):
        return np.array([]), np.array([])
    first, delta, lo, hi = first[indices], delta[indices], lo[indices], hi[indices]
    gap = np.ones(len(indices), dtype=bool)
    gap[1:] = (np.diff(indices) != 1) | (lo[1:] > 0) | (hi[:-1] < 1)
    paths = np.full((len(indices), 3, 2), np.nan)
    paths[:, 1] = np.clip(first + lo[:, None] * delta, lower, upper)
    paths[:, 2] = np.clip(first + hi[:, None] * delta, lower, upper)
    keep = np.column_stack((gap, gap, np.ones(len(indices), dtype=bool)))
    clipped = paths[keep]
    return clipped[:, 0], clipped[:, 1]


def validate_breaks(trace, settings):
    for name, omitted, limits in zip((trace.x_label, "Signal"), (settings.x_break, settings.y_break), view_limits(trace, settings)):
        if omitted is None:
            continue
        if len(omitted) != 2 or not all(math.isfinite(v) for v in omitted) or omitted[0] >= omitted[1]:
            raise ValueError(f"{name} break needs two finite values with From < To.")
        if not limits[0] < omitted[0] < omitted[1] < limits[1]:
            raise ValueError(f"{name} break must lie strictly inside the visible range ({limits[0]:.9g}, {limits[1]:.9g}).")
    if settings.x_break:
        from gcviewer.figures.workspace import source_traces
        lo, hi = view_limits(trace, settings)[0]
        a, b = settings.x_break
        if not any(np.any((t.time >= lo) & (t.time <= hi) & ((t.time <= a) | (t.time >= b))) for t in source_traces(trace)):
            raise ValueError("The X break hides every data point. Narrow the break.")


def display_path(trace, xlim=None, ylim=None, *, settings=None):
    """Chromatogram polylines or independent mass sticks, clipped for SVG."""
    signal = display_signal(trace, settings) if settings is not None else trace.signal
    if trace.plot_kind == "line":
        return clipped_path(trace.time, signal, xlim, ylim) if xlim is not None else (trace.time, signal)
    x, y = trace.time, signal
    lower, upper = np.minimum(y, 0), np.maximum(y, 0)
    if xlim is not None:
        keep = (x >= xlim[0]) & (x <= xlim[1]) & (upper >= ylim[0]) & (lower <= ylim[1])
        x, lower, upper = x[keep], np.maximum(lower[keep], ylim[0]), np.minimum(upper[keep], ylim[1])
    return (np.column_stack((np.full(len(x), np.nan), x, x)).ravel(),
            np.column_stack((np.full(len(x), np.nan), lower, upper)).ravel())


def make_panels(fig, ax, trace, settings, font, series=None):
    """Return bottom-left primary axis first, plus a whole-plot text transform."""
    from matplotlib.transforms import Bbox, BboxTransformTo
    series = series or ((trace, settings.color),)
    xlim, ylim = view_limits(trace, settings)
    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    ax.report_column = ax.report_row = 0
    if not settings.x_break and not settings.y_break:
        return [ax], ax.transAxes
    rectangle = ax.get_position().frozen()
    label_transform = BboxTransformTo(rectangle) + fig.transFigure
    xs, ys = intervals(xlim, settings.x_break), intervals(ylim, settings.y_break)
    xgap = 1.2 * font / 10 / settings.width_mm if settings.x_break else 0
    ygap = 1.2 * font / 10 / settings.height_mm if settings.y_break else 0
    xspan = sum(hi - lo for lo, hi in xs)
    yspan = sum(hi - lo for lo, hi in ys)
    widths = [(rectangle.width - xgap) * (hi - lo) / xspan for lo, hi in xs]
    heights = [(rectangle.height - ygap) * (hi - lo) / yspan for lo, hi in ys]
    panels = []
    for row, yrange in enumerate(ys):
        for column, xrange in enumerate(xs):
            panel = ax if row == column == 0 else fig.add_axes(rectangle.bounds)
            for index, (item, color) in enumerate(series):
                path = display_path(item, xrange, yrange, settings=settings)
                if panel is not ax:
                    panel.plot(*path, color=color, linewidth=settings.line_width)
                else:
                    panel.lines[index].set_data(*path)
            panel.set_position(Bbox.from_bounds(rectangle.x0 + sum(widths[:column]) + column * xgap,
                               rectangle.y0 + sum(heights[:row]) + row * ygap, widths[column], heights[row]))
            panel.set_xlim(xrange)
            panel.set_ylim(yrange)
            panel.report_column, panel.report_row = column, row
            for side in ("top", "right"):
                panel.spines[side].set_visible(False)
            panel.spines["left"].set_visible(column == 0)
            panel.spines["bottom"].set_visible(row == 0)
            for side in ("left", "bottom"):
                panel.spines[side].set_linewidth(.6)
            panel.tick_params(left=column == 0, labelleft=column == 0, bottom=row == 0, labelbottom=row == 0)
            from matplotlib.patheffects import Stroke, Normal
            marker = dict(marker=[(-1, -1.2), (1, 1.2)], markersize=6 * font / 10,
                          linestyle="none", color="#20252b", mec="#20252b", mew=.7,
                          transform=panel.transAxes, clip_on=False, zorder=5,
                          path_effects=[Stroke(linewidth=2.2 * font / 10, foreground="white"), Normal()])
            if settings.x_break and row == 0:
                edge = 1 if column == 0 else 0
                marks, = panel.plot([edge], [0], **marker)
                marks.set_gid("x-axis-break")
            if settings.y_break and column == 0:
                edge = 1 if row == 0 else 0
                marks, = panel.plot([0], [edge], **marker)
                marks.set_gid("y-axis-break")
            panels.append(panel)
    ax.set_title(settings.title, x=rectangle.width / (2 * widths[0]),
                 y=rectangle.height / heights[0], pad=10 * font / 10)
    ax.xaxis.set_label_coords(rectangle.width / (2 * widths[0]),
                             -9 * font / 10 / settings.height_mm / heights[0])
    ax.yaxis.set_label_coords(-10 * font / 10 / settings.width_mm / widths[0],
                             rectangle.height / (2 * heights[0]))
    return panels, label_transform


def style_ticks(ax, trace, settings, display, font, family):
    from matplotlib.ticker import FuncFormatter, MaxNLocator
    ax.tick_params(labelsize=font, labelfontfamily=family, width=.6,
                   length=3.5 * font / 10, pad=3.5 * font / 10)
    broken = bool(settings.x_break or settings.y_break)
    if broken:
        width = ax.get_position().width * settings.width_mm
        height = ax.get_position().height * settings.height_mm
        xprune = ("upper" if ax.report_column == 0 else "lower") if settings.x_break else None
        yprune = ("upper" if ax.report_row == 0 else "lower") if settings.y_break else None
        ax.xaxis.set_major_locator(MaxNLocator(nbins=max(2, int(width / (font * 2))), min_n_ticks=2, prune=xprune))
        ax.yaxis.set_major_locator(MaxNLocator(nbins=max(2, int(height / (font * .9))), min_n_ticks=2, prune=yprune))
        ax.ticklabel_format(axis="x", style="plain", useOffset=False)
    if settings.y_numbers == "readable":
        def readable_tick(value, _):
            ticks = np.asarray(ax.get_yticks()) / display["divisor"]
            steps = np.diff(np.unique(ticks))
            steps = steps[steps > 0]
            extent = float(np.max(np.abs(ticks))) if len(ticks) else 0
            digits = 6
            if len(steps) and extent:
                digits = max(digits, math.ceil(math.log10(extent)) - math.floor(math.log10(float(steps.min()))) + 2)
            return f"{value / display['divisor']:,.{min(17, digits)}g}"
        ax.yaxis.set_major_formatter(FuncFormatter(readable_tick))
    else:
        powers = (-3, 4)
        style = "sci" if settings.y_numbers == "scientific" else "plain"
        if broken and settings.y_numbers == "scientific":
            maximum = max(abs(v) for v in view_limits(trace, settings)[1])
            exponent = math.floor(math.log10(maximum)) if maximum else 0
            if exponent <= -3 or exponent >= 4:
                powers = (exponent, exponent)
            else:
                style = "plain"
        ax.ticklabel_format(axis="y", style=style,
                            scilimits=powers, useOffset=False, useMathText=True)
    for axis in (ax.xaxis, ax.yaxis):
        axis.get_offset_text().set_fontsize(font)
        axis.get_offset_text().set_fontfamily(family)
    if broken:
        ax.yaxis.get_offset_text().set_visible(ax.report_column == 0 and ax.report_row == bool(settings.y_break))

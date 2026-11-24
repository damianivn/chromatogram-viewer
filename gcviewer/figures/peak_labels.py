"""Presentation-only peak annotation candidates and initial text placement."""
import numpy as np
from scipy.signal import find_peaks

from gcviewer.figures.workspace import PeakLabel, source_traces, render_figure
from gcviewer.analysis.processing import display_signal


def automatic_labels(trace, settings, *, trace_index=0, record=None, mode='top', count=10,
                     threshold=10., prominence=1., text_mode='rt'):
    """Detect in the displayed signal, or reuse verified FID peak apex indices.

    Filtering is against the full-trace maximum; axes only determine visibility.
    FID retention times retain their fitted values while arrows use sample indices.
    """
    source = source_traces(trace)[trace_index]
    if source.x_unit != 'min' or source.plot_kind != 'line':
        raise ValueError('Automatic labels are available for chromatograms.')
    if mode not in ('top', 'threshold') or text_mode not in ('rt', 'name', 'both'):
        raise ValueError('Choose a supported label selection and text mode.')
    if not 1 <= count <= 100 or not all(np.isfinite(v) and 0 <= v <= 100 for v in (threshold, prominence)):
        raise ValueError('Use 1–100 labels and percentages between 0 and 100.')
    signal = display_signal(source, settings)
    maximum = float(np.max(signal))
    if record is None:
        if text_mode != 'rt':
            raise ValueError('Names require a current FID integration with assigned components.')
        indices, _ = find_peaks(signal, prominence=float(np.ptp(signal)) * prominence / 100.)
        candidates = [(int(i), float(source.time[i]), '') for i in indices]
    else:
        candidates = [(int(p['apex']), float(p['rt_min']), record['names'].get(str(p['number']), ''))
                      for p in record['peaks']]
    def retained(candidate):
        i, x, name = candidate
        if not 0 <= i < len(signal):
            raise ValueError('Integrated peak anchor does not belong to this trace.')
        x, y = float(source.time[i]), float(signal[i])
        return ((text_mode != 'name' or bool(name)) and
                (settings.x_range is None or settings.x_range[0] <= x <= settings.x_range[1]) and
                (settings.y_range is None or settings.y_range[0] <= y <= settings.y_range[1]) and
                not (settings.x_break and settings.x_break[0] < x < settings.x_break[1]) and
                not (settings.y_break and settings.y_break[0] < y < settings.y_break[1]))
    candidates = [c for c in candidates if retained(c)]
    candidates.sort(key=lambda c: (-float(signal[c[0]]), c[0]))
    if mode == 'top':
        candidates = candidates[:count]
    else:
        candidates = [c for c in candidates if signal[c[0]] >= maximum * threshold / 100.]
        if len(candidates) > 100:
            raise ValueError('More than 100 labels match. Increase the threshold or prominence, or use Top N.')
    generation = dict(source='FID integration' if record is not None else 'displayed-signal detection',
                      mode=mode, count=count if mode == 'top' else None,
                      threshold_percent=threshold if mode == 'threshold' else None,
                      prominence_percent=prominence if record is None else None, text_mode=text_mode,
                      smoothing_window=settings.smoothing_window, normalized=settings.normalize,
                      analysis_key=record['analysis_key'] if record is not None else None)
    labels = []
    for index, rt, name in sorted(candidates):
        text = f'{rt:.2f} min'
        if text_mode == 'name': text = name
        elif text_mode == 'both' and name: text = f'{name}\n{text}'
        labels.append(PeakLabel(index, text, trace_index=trace_index, origin='automatic',
                                generation={**generation, 'assigned_name': name, 'retention_time_min': rt}))
    return labels


def arrange_labels(trace, state, generated):
    """Place new labels using actual rendered text extents at final figure size.

    Preserve other labels; return the count that cannot fit without overlap.
    Stored positions are shared by the Qt preview and every export format.
    """
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.text import Text
    from matplotlib.transforms import Bbox
    fig, _, artists = render_figure(trace, state)
    canvas = FigureCanvasAgg(fig)
    canvas.draw()
    renderer = canvas.get_renderer()
    transform = fig.report_label_transform
    area = transform.transform_bbox(Bbox.from_extents(0., 0., 1., 1.))
    fresh = {id(label) for label in generated}
    occupied = [Text.get_window_extent(a, renderer).expanded(1.08, 1.15)
                for label, a in zip(state.labels, artists) if a is not None and id(label) not in fresh]
    crowded = 0
    for label, artist in zip(state.labels, artists):
        if artist is None or id(label) not in fresh:
            continue
        box = Text.get_window_extent(artist, renderer).expanded(1.08, 1.15)
        half_w, half_h = box.width / 2, box.height / 2
        anchor_x, anchor_y = artist.axes.transData.transform(artist.xy)
        found = None
        if box.width < area.width and box.height < area.height:
            xs = np.linspace(area.x0 + half_w, area.x1 - half_w, 35)
            xs = sorted(set([float(np.clip(anchor_x, xs[0], xs[-1])), *xs]), key=lambda x: abs(x-anchor_x))
            bottom = min(area.y1-half_h, max(area.y0+half_h, anchor_y+half_h+fig.dpi*.08))
            ys = np.arange(bottom, area.y1-half_h+1., max(box.height * 1.2, 1.))
            positions = sorted(((x, y) for x in xs for y in ys),
                               key=lambda p: (1.5*(p[0]-anchor_x))**2 + (p[1]-anchor_y)**2)
            for x, y in positions:
                candidate = Bbox.from_bounds(x-half_w, y-half_h, box.width, box.height)
                if not any(candidate.overlaps(other) for other in occupied):
                    found = (x, y, candidate)
                    break
        if found:
            x, y, candidate = found
            label.position = tuple(float(v) for v in transform.inverted().transform((x, y)))
            occupied.append(candidate)
        else:
            crowded += 1
    fig.clear()
    return crowded

"""Publication starting points. Journal requirements still govern submissions."""
from dataclasses import dataclass


@dataclass(frozen=True)
class FigureStyle:
    label: str
    single_mm: float
    double_mm: float
    text_pt: float | None
    raster_dpi: int
    guidance: str
    source_url: str


FIGURE_STYLES = {
    "general": FigureStyle("General", 90, 180, None, 300,
        "Layout-aware 7–10 pt Arial. Editable dimensions and fixed text size are available. "
        "PDF is preferred for sharp lines and embedded fonts; PNG is useful for reports. "
        "These are application defaults, not a journal compliance certificate.",
        "https://www.elsevier.com/about/policies-and-standards/author/artwork-and-media-instructions/artwork-overview"),
    "analytical_chemistry": FigureStyle("Analytical Chemistry (ACS)", 84.6, 177.8, 8, 1200,
        "Arial, 8 pt throughout; 84.6 mm single or 177.8 mm double column. "
        "The 8 pt size is our readable default, above ACS's 4.5 pt minimum; lines must be at least 0.5 pt. "
        "ACS specifies 1200 dpi for black-and-white line art. Use PDF or TIFF as appropriate to the submission. "
        "Maximum graphic plus caption height is 232.8 mm. Keep captions in the manuscript. "
        "Layout heights are application choices; custom edits may exceed this guidance.",
        "https://researcher-resources.acs.org/publish/author_guidelines?coden=ancham"),
    "chromatography": FigureStyle("Chromatography (Elsevier)", 90, 190, 8, 1000,
        "Arial, 8 pt throughout; 90 mm single or 190 mm double column. "
        "The 8 pt size is our default; Elsevier suggests about 7 pt at final size. "
        "PDF embeds fonts; TIFF line art uses 1000 dpi. Use consistent lettering and separate captions. "
        "Based on Elsevier's general artwork guidance. Check the current target journal's instructions "
        "for exceptions, including Journal of Chromatography A.",
        "https://www.elsevier.com/about/policies-and-standards/author/artwork-and-media-instructions/artwork-sizing"),
}


def figure_size_presets(style="general"):
    spec = FIGURE_STYLES[style]
    sizes = (("Report", spec.double_mm, 110), ("Single column", spec.single_mm, 70),
             ("Double column", spec.double_mm, 120),
             ("Landscape", spec.double_mm, round(spec.double_mm / 2, 1)),
             ("Wide", spec.double_mm, round(spec.double_mm / 3, 1)))
    return (("Custom dimensions", None),) + tuple(
        (f"{name} · {width:g} × {height:g} mm", (width, height)) for name, width, height in sizes)

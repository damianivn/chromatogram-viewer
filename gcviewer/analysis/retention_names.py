"""Peak identification: name integrated peaks from a component table (name, RT, window).

Rule: components are taken in order of expected retention time; each claims the
closest still-unnamed peak whose RT lies within its window. A peak is named at most once.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

from gcviewer.analysis.totalchrom_fid import IntegrationResult


@dataclass(frozen=True)
class Component:
    name: str
    rt_min: float
    window_min: float = 0.05

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("component name is empty")
        if not math.isfinite(self.rt_min) or self.rt_min < 0:
            raise ValueError("component retention time must be finite and nonnegative")
        if not math.isfinite(self.window_min) or self.window_min <= 0:
            raise ValueError("component window must be positive")

    def to_dict(self) -> dict:
        return {"name": self.name, "rt_min": self.rt_min, "window_min": self.window_min}

    @classmethod
    def from_dict(cls, d: dict) -> "Component":
        return cls(str(d["name"]), float(d["rt_min"]), float(d.get("window_min", 0.05)))


def identify(result: IntegrationResult, components: Iterable[Component]
             ) -> tuple[dict[int, str], list[str]]:
    """Return ({peak number: component name}, [components not found])."""
    names: dict[int, str] = {}
    missing: list[str] = []
    for comp in sorted(components, key=lambda c: c.rt_min):
        candidates = [p for p in result.peaks
                      if p.number not in names and abs(p.rt_min - comp.rt_min) <= comp.window_min]
        if candidates:
            best = min(candidates, key=lambda p: abs(p.rt_min - comp.rt_min))
            names[best.number] = comp.name
        else:
            missing.append(comp.name)
    return names, missing

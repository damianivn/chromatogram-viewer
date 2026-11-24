"""Cheap discovery of TotalChrom RAW files without decoding the acquisition."""
from __future__ import annotations

import os
from pathlib import Path


from gcviewer.parsers.totalchrom.raw import FILE_TYPE_RAW


def is_penx_file(filepath: str | os.PathLike) -> bool:
    try:
        p = Path(filepath)
        if not p.is_file() or p.stat().st_size < 16:
            return False
        with p.open("rb") as f:
            head = f.read(8)
        return head[:4] == b"PENX" and int.from_bytes(head[4:8], "big") == FILE_TYPE_RAW
    except OSError:
        return False


def find_raw_files(folder: str | os.PathLike) -> list[str]:
    try:
        names = sorted(e for e in os.listdir(folder) if e.lower().endswith(".raw"))
    except OSError:
        return []
    return [n for n in names if is_penx_file(os.path.join(folder, n))]



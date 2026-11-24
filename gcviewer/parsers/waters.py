"""
Waters / Perkin-Elmer GC-MS Data Parser
=======================================
Thin wrapper around rainbow-api for GC-MS .raw directories
(MassLynx-style layout, including Perkin-Elmer TurboMass exports).
No Streamlit dependency — can be used standalone.
"""

import os


def load_raw(filepath):
    """Load a Waters .raw directory via rainbow. Returns DataDirectory."""
    import rainbow as rb
    return rb.read(filepath)


def find_raw_dirs(folder):
    """Find .raw directories (Waters MassLynx format) in a folder."""
    try:
        return sorted(e for e in os.listdir(folder)
                      if os.path.isdir(os.path.join(folder, e))
                      and e.lower().endswith(".raw"))
    except Exception:
        return []



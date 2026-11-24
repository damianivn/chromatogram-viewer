"""TIC/EIC array calculations with explicit smoothing options."""
import numpy as np
from scipy.ndimage import uniform_filter1d


def get_tic(df, rtr=None, sm=5, norm=False):
    """
    Extract TIC from a rainbow DataFile.
    Returns (rt, tic) numpy arrays.
    """
    rt = df.xlabels.copy()
    tic = df.data.sum(axis=1).astype(float)
    if sm > 1:
        tic = uniform_filter1d(tic, sm)
    if rtr and rtr[0] < rtr[1]:
        m = (rt >= rtr[0]) & (rt <= rtr[1])
        rt, tic = rt[m], tic[m]
    if norm:
        mx = tic.max()
        if mx > 0:
            tic = tic / mx * 100
    return rt, tic


def get_eic(df, mz, rtr=None, sm=5):
    """
    Extract EIC for a given m/z from a rainbow DataFile.
    Returns (rt, eic, actual_mz) numpy arrays.
    """
    rt = df.xlabels.copy()
    idx = np.abs(df.ylabels - mz).argmin()
    amz = df.ylabels[idx]
    eic = df.data[:, idx].astype(float)
    if sm > 1:
        eic = uniform_filter1d(eic, sm)
    if rtr and rtr[0] < rtr[1]:
        m = (rt >= rtr[0]) & (rt <= rtr[1])
        rt, eic = rt[m], eic[m]
    return rt, eic, amz

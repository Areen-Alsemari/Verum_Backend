"""Statistics of the agent-side audit: window means and slopes, calibrated thresholds, classes.

A run is held as sums and counts of the observed values in blocks of equal length. Window means and
least-squares slopes follow exactly from the blocks. A threshold is a percentile, over healthy runs,
of the largest deviation of a feature from its healthy mean; the margin of a faulted run is its
largest deviation over that threshold. Classes and boundaries are read from the margins.

See D79 to D81.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

BLOCK_S = 10.0
GRID_S = 60.0
N_ENDS = 45
HELD_WINDOWS = 3
INVISIBLE_BELOW = 1.0
CLEAR_FROM = 3.0


def window_ends() -> np.ndarray:
    """End times of the windows, on a grid of 60 s."""
    return np.arange(1, N_ENDS + 1) * GRID_S


def window_stats(
    sums: np.ndarray, counts: np.ndarray, length_s: int, min_fill: float = 0.5
) -> tuple[np.ndarray, np.ndarray]:
    """Window mean and least-squares slope (per second) of a tag, NaN where a window is short.

    The slope is the regression of the block means on the block centres, weighted by the counts,
    so it equals the regression of the readings up to the position of each reading in its block.
    A window with fewer than ``min_fill`` of its expected readings has no value.
    """
    n = len(sums)
    centre = (np.arange(n) + 0.5) * BLOCK_S
    mean_block = np.divide(sums, counts, out=np.zeros(n), where=counts > 0)

    def cum(v: np.ndarray) -> np.ndarray:
        return np.concatenate(([0.0], np.cumsum(v)))

    sw = cum(counts)
    swc, swcc = cum(counts * centre), cum(counts * centre**2)
    swx, swcx = cum(counts * mean_block), cum(counts * centre * mean_block)
    hi = (window_ends() / BLOCK_S).astype(int)
    lo = hi - int(length_s / BLOCK_S)
    ok = lo >= 0
    lo = np.where(ok, lo, 0)
    w, wc, wcc, wx, wcx = (a[hi] - a[lo] for a in (sw, swc, swcc, swx, swcx))
    enough = ok & (w >= min_fill * length_s / BLOCK_S)
    safe = np.where(w == 0, 1.0, w)
    mean = np.where(enough, wx / safe, np.nan)
    den = wcc - wc**2 / safe
    good = enough & (den > 0)
    slope = np.where(good, (wcx - wc * wx / safe) / np.where(good, den, 1.0), np.nan)
    return mean, slope


def mass_balance(
    flow_in: np.ndarray, flow_out: np.ndarray, level_slopes_m_s: list[np.ndarray], area_m2: float
) -> np.ndarray:
    """Inflow minus outflow minus the rate of change of the summed tank volume, in m3/h."""
    rate = np.sum(np.stack(level_slopes_m_s), axis=0) * area_m2 * 3600.0
    return np.asarray(flow_in - flow_out - rate)


@dataclass
class Threshold:
    mean: float
    value: float
    error: float  # standard error of the percentile, by bootstrap over runs
    runs: int


def deviation_maxima(series: np.ndarray, mean: float) -> np.ndarray:
    """Largest absolute deviation from ``mean`` over the last axis, NaN if no window is valid."""
    dev = np.abs(series - mean)
    largest = np.where(np.isfinite(dev), dev, -np.inf).max(axis=-1)
    return np.where(np.isneginf(largest), np.nan, largest)


def calibrate(
    series: np.ndarray, percentile: float = 99.0, boot: int = 200, seed: int = 1
) -> Threshold:
    """Threshold of one feature from healthy series of shape (runs, draws, windows)."""
    mean = float(series[np.isfinite(series)].mean())
    maxima = deviation_maxima(series, mean)
    runs = maxima.shape[0]
    rng = np.random.default_rng(seed)
    resampled = [
        float(np.nanpercentile(maxima[rng.integers(0, runs, runs)], percentile))
        for _ in range(boot)
    ]
    return Threshold(
        mean, float(np.nanpercentile(maxima, percentile)), float(np.std(resampled, ddof=1)), runs
    )


def exceedance(series: np.ndarray, mean: float, threshold: float) -> np.ndarray:
    """Deviation over the threshold for each window; a missing window counts as zero."""
    z = np.abs(series - mean) / threshold
    return np.where(np.isfinite(z), z, 0.0)


def held(z: np.ndarray, windows: int = HELD_WINDOWS) -> np.ndarray:
    """The margin held over ``windows`` consecutive windows, at the last of them (zero before)."""
    out = np.zeros_like(z)
    shifted = [z[i : len(z) - windows + 1 + i] for i in range(windows)]
    out[windows - 1 :] = np.min(np.stack(shifted), axis=0)
    return out


def klass(margin: float) -> str:
    """Invisible below 1, marginal from 1 to below 3, clear from 3."""
    if margin < INVISIBLE_BELOW:
        return "invisible"
    return "marginal" if margin < CLEAR_FROM else "clear"


def crossing(points: list[tuple[float, float]], level: float) -> float | None:
    """Severity at which the margin first reaches ``level``, by log-log interpolation.

    ``points`` are (severity, margin) pairs with the most severe last. A severity may be stored
    with its sign flipped when it grows as the physical value falls; the sign is kept.
    """
    if points[0][1] >= level:
        return points[0][0]
    for (x0, m0), (x1, m1) in zip(points, points[1:], strict=False):
        if m0 < level <= m1:
            if m0 <= 0:
                return x1
            f = (math.log(level) - math.log(m0)) / (math.log(m1) - math.log(m0))
            sign = -1.0 if x0 < 0 else 1.0
            return sign * math.exp(math.log(abs(x0)) + f * (math.log(abs(x1)) - math.log(abs(x0))))
    return None

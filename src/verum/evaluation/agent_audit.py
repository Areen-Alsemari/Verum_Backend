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
        mean,
        float(np.nanpercentile(maxima, percentile)),
        float(np.std(resampled, ddof=1)) if boot > 1 else 0.0,
        runs,
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


HELD_OUT_PREFIX = "held|"


def block_series(sums: np.ndarray, counts: np.ndarray) -> np.ndarray:
    """Block means with the empty blocks filled by linear interpolation in time."""
    mean = np.divide(sums, counts, out=np.full(len(sums), np.nan), where=counts > 0)
    index = np.arange(len(mean))
    valid = np.isfinite(mean)
    return np.asarray(np.interp(index, index[valid], mean[valid]))


def equal_weight_slopes(y: np.ndarray, length_s: int) -> np.ndarray:
    """Least-squares slope per second of a block series in each window, equal weights."""
    k = int(length_s / BLOCK_S)
    t = (np.arange(len(y)) + 0.5) * BLOCK_S
    out = np.full(N_ENDS, np.nan)
    for i, hi in enumerate((window_ends() / BLOCK_S).astype(int)):
        lo = hi - k
        if lo >= 0:
            tw, yw = t[lo:hi] - t[lo:hi].mean(), y[lo:hi]
            out[i] = float(np.sum(tw * (yw - yw.mean())) / np.sum(tw * tw))
    return out


def passed_volume_m3(flow_m3h: np.ndarray) -> np.ndarray:
    """Volume that has passed up to the centre of each block, from block mean flows."""
    increment = flow_m3h * BLOCK_S / 3600.0
    return np.cumsum(increment) - 0.5 * increment


def matched_mass_balance(
    inflow: tuple[np.ndarray, np.ndarray],
    outflow: tuple[np.ndarray, np.ndarray],
    tanks: list[tuple[np.ndarray, np.ndarray]],
    area_m2: float,
    length_s: int,
) -> np.ndarray:
    """Inflow minus outflow minus tank volume rate, with the three volumes regressed alike.

    Each argument is a (sums, counts) pair per block. The result is in m3/h; a change of flow
    inside the window enters the three slopes with the same weights and cancels.
    """
    v_in = passed_volume_m3(block_series(*inflow))
    v_out = passed_volume_m3(block_series(*outflow))
    v_tank = area_m2 * np.sum([block_series(*t) for t in tanks], axis=0)
    return equal_weight_slopes(v_in - v_out - v_tank, length_s) * 3600.0


def run_margin(ratios: np.ndarray) -> np.ndarray:
    """Margin of each healthy run: largest ratio over features, smallest over the design draws.

    ``ratios`` has shape (features, runs, draws), each entry a deviation over its threshold.
    """
    return np.asarray(np.min(np.max(ratios, axis=0), axis=-1))


def scale_factor(margins: np.ndarray, max_rate: float = 0.01) -> float:
    """Smallest factor for which at most ``max_rate`` of the runs have a margin above it."""
    allowed = int(np.floor(max_rate * len(margins)))
    return float(np.sort(margins)[::-1][allowed])


def check_calibration_labels(labels: list[str]) -> None:
    """Refuse a derivation whose inputs include a held-out run."""
    held_out = [label for label in labels if label.startswith(HELD_OUT_PREFIX)]
    if held_out:
        raise ValueError(f"held-out runs are not inputs of a threshold or a scale: {held_out[:3]}")


def folds(count: int, number: int, rng: np.random.Generator) -> list[np.ndarray]:
    """A random partition of ``count`` run indices into ``number`` folds."""
    return [np.sort(part) for part in np.array_split(rng.permutation(count), number)]

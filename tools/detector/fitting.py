"""Fault-free baselines: robust location and scale per regime, PCA with limits, quadratic fits.

Everything here is fitted on fault-free train windows. A regime with fewer than MIN_REGIME
windows, and any regime never seen in training, uses the pooled baseline. There is no novelty
score: an unseen regime is compared with the pooled baseline like any other window.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

Floats = NDArray[np.float64]
Regime = tuple[int, ...]
MIN_REGIME = 200
MAD_FACTOR = 1.4826


def median_scale(x: Floats, floor_range: Floats) -> tuple[Floats, Floats]:
    """Median and robust scale along axis 0, with a floor taken from a pooled range."""
    med = np.nanmedian(x, axis=0)
    mad = np.nanmedian(np.abs(x - med), axis=0)
    return med, np.maximum(MAD_FACTOR * mad, 1e-6 + 0.01 * floor_range)


def pooled_range(x: Floats) -> Floats:
    """Spread between the 1st and 99th percentile along axis 0, ignoring NaN."""
    lo, hi = np.nanpercentile(x, [1, 99], axis=0)
    return np.asarray(hi - lo, dtype=np.float64)


@dataclass
class Baseline:
    """Median and scale of the window statistics, per regime and pooled."""

    pooled: tuple[Floats, Floats]
    by_regime: dict[Regime, tuple[Floats, Floats]]
    floor: Floats

    def params(self, regimes: list[Regime]) -> tuple[Floats, Floats]:
        """Median and scale for every window, shape like the statistics array."""
        med = np.empty((len(regimes), *self.pooled[0].shape))
        scale = np.empty_like(med)
        for r in set(regimes):
            m, s = self.by_regime.get(r, self.pooled)
            idx = [i for i, q in enumerate(regimes) if q == r]
            med[idx], scale[idx] = m, s
        return med, scale

    def standardise(self, x: Floats, regimes: list[Regime]) -> Floats:
        """z-scores; a missing value becomes 0, i.e. no evidence."""
        med, scale = self.params(regimes)
        return np.nan_to_num((x - med) / scale, nan=0.0)


def fit_baseline(x: Floats, regimes: list[Regime]) -> Baseline:
    """Fit the pooled baseline and one per regime with at least MIN_REGIME windows."""
    floor = pooled_range(x)
    counts = Counter(regimes)
    by_regime = {}
    for r, count in counts.items():
        if count >= MIN_REGIME:
            mask = np.asarray([q == r for q in regimes])
            by_regime[r] = median_scale(x[mask], floor)
    return Baseline(median_scale(x, floor), by_regime, floor)


@dataclass
class Pca:
    """PCA on standardised columns with T-squared and SPE limits from fault-free data."""

    mean: Floats
    comps: Floats
    eig: Floats
    t2_limit: float
    spe_limit: float

    def parts(self, z: Floats) -> tuple[Floats, Floats, Floats, Floats]:
        """T-squared, SPE, per-column residual squares and per-column T-squared shares."""
        c = z - self.mean
        t = c @ self.comps
        resid = c - t @ self.comps.T
        weighted = (t / self.eig) @ self.comps.T
        return (t**2 / self.eig).sum(axis=1), (resid**2).sum(axis=1), resid**2, c * weighted

    def ratios(self, z: Floats) -> tuple[Floats, Floats]:
        """T-squared and SPE divided by their limits."""
        t2, spe, _, _ = self.parts(z)
        return t2 / self.t2_limit, spe / self.spe_limit


def fit_pca(z: Floats, variance: float = 0.95, limit_q: float = 99.0) -> Pca:
    """Fit on fault-free columns; keep the fewest components explaining the variance."""
    mean = z.mean(axis=0)
    _, sv, vt = np.linalg.svd(z - mean, full_matrices=False)
    var = sv**2 / (len(z) - 1)
    k = int(np.searchsorted(np.cumsum(var) / var.sum(), variance) + 1)
    k = min(max(k, 1), len(var))
    model = Pca(mean, vt[:k].T, np.maximum(var[:k], 1e-12), 1.0, 1.0)
    t2, spe, _, _ = model.parts(z)
    model.t2_limit = float(np.percentile(t2, limit_q))
    model.spe_limit = float(max(np.percentile(spe, limit_q), 1e-12))
    return model


def fit_quadratic(q: Floats, y: Floats) -> Floats:
    """Least-squares coefficients of y = c0 + c1 q + c2 q^2."""
    return np.asarray(np.polyfit(q, y, 2)[::-1], dtype=np.float64)


def predict_quadratic(coef: Floats, q: Floats) -> Floats:
    """Value of the quadratic fit."""
    return np.asarray(coef[0] + coef[1] * q + coef[2] * q**2, dtype=np.float64)

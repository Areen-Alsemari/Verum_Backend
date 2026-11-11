"""The four candidates: per-tag baseline with CUSUM, PCA monitoring, topology residuals, fusion.

All are fitted on fault-free train windows only. Each scoring call returns the window score and
a matrix of per-tag (or per-residual) contributions, used for the top-contributor control.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import numpy as np
from fitting import (
    MIN_REGIME,
    Baseline,
    Floats,
    Pca,
    fit_baseline,
    fit_pca,
    fit_quadratic,
    median_scale,
    pooled_range,
    predict_quadratic,
)
from numpy.typing import NDArray
from windows import BOOL_TAGS, NUMERIC_TAGS, Windows

TOP_K = 3
GROUPS = {
    "receipt": ["FT-001", "PT-001", "TT-001"],
    "storage": ["LT-101", "LT-102", "LT-103", "TT-101", "TT-102", "TT-103"],
    "transfer": ["PT-201", "PT-202A", "PT-202B", "PT-203", "FT-201"],
}
TAG = {t: i for i, t in enumerate(NUMERIC_TAGS)}
PUMP_A, PUMP_B = BOOL_TAGS.index("P-101A"), BOOL_TAGS.index("P-101B")
SHIFT_TAGS = ("TT-001", "TT-101", "TT-102", "TT-103")
SHIFT_IDX = [NUMERIC_TAGS.index(t) for t in SHIFT_TAGS]


@dataclass
class Scored:
    """Window scores and the contribution of each tag or residual to them."""

    scores: Floats
    parts: Floats
    names: list[str]
    tags: Floats | None = None


class PerTag:
    """C1: robust z-scores of level, slope and spread per tag, plus CUSUM, top-3 mean."""

    def __init__(self, train: Windows, base: Baseline | None = None) -> None:
        self.base: Baseline = base or fit_baseline(train.x, train.regime)
        self.cusum: tuple[Floats, Floats] | None = None

    def cusum_params(self, w: Windows) -> tuple[Floats, Floats]:
        """Centre and sample scale of the raw series for every window and tag."""
        med, scale = self.base.params(w.regime)
        return med[:, :, 0], np.sqrt(scale[:, :, 0] ** 2 + med[:, :, 2] ** 4)

    def calibrate(self, stats: Floats) -> None:
        """Standardise log(1 + CUSUM maximum) on fault-free train windows, pooled over regimes."""
        c = np.log1p(stats)
        self.cusum = median_scale(c, pooled_range(c))

    def score(self, w: Windows, stats: Floats | None, guard: bool = False) -> Scored:
        """Per-tag maximum of the components; window score is the top-3 mean.

        With guard, the level and CUSUM components of the temperature tags are set to zero.
        Without CUSUM statistics (stats is None) only the three window statistics are used.
        """
        zfull = np.abs(self.base.standardise(w.x, w.regime))
        zc = np.zeros(zfull.shape[:2])
        if stats is not None:
            assert self.cusum is not None
            zc = np.abs(np.nan_to_num((np.log1p(stats) - self.cusum[0]) / self.cusum[1], nan=0.0))
        if guard:
            zfull[:, SHIFT_IDX, 0] = 0.0
            zc[:, SHIFT_IDX] = 0.0
        z = zfull.max(axis=2)
        per_tag = np.maximum(z, zc)
        top = np.sort(per_tag, axis=1)[:, -TOP_K:].mean(axis=1)
        return Scored(top, per_tag, list(NUMERIC_TAGS), per_tag)


def _columns(z: Floats, tags: list[str]) -> Floats:
    idx = [TAG[t] for t in tags]
    return z[:, idx, :].reshape(len(z), -1)


class PcaMonitor:
    """C2: PCA per regime (pooled below the minimum), T-squared and SPE over their limits."""

    def __init__(
        self, train: Windows, base: Baseline, groups: dict[str, list[str]], guard: bool = False
    ) -> None:
        self.base, self.groups, self.guard = base, groups, guard
        z = self._z(train)
        self.models: dict[tuple[str, object], Pca] = {}
        counts = {r: train.regime.count(r) for r in set(train.regime)}
        for name, tags in groups.items():
            cols = _columns(z, tags)
            self.models[(name, None)] = fit_pca(cols)
            for r, c in counts.items():
                if c >= MIN_REGIME:
                    mask = np.asarray([q == r for q in train.regime])
                    self.models[(name, r)] = fit_pca(cols[mask])

    def _z(self, w: Windows) -> Floats:
        """Standardised columns; with guard the temperature level columns are set to zero."""
        z = self.base.standardise(w.x, w.regime)
        if self.guard:
            z[:, SHIFT_IDX, 0] = 0.0
        return z

    def _group(
        self, name: str, z: Floats, regimes: list[tuple[object, ...]]
    ) -> tuple[Floats, Floats]:
        cols = _columns(z, self.groups[name])
        score = np.zeros(len(z))
        contrib = np.zeros((len(z), len(self.groups[name])))
        for r in set(regimes):
            idx = np.asarray([i for i, q in enumerate(regimes) if q == r])
            pca = self.models.get((name, r), self.models[(name, None)])
            t2, spe, resid, share = pca.parts(cols[idx])
            score[idx] = np.maximum(t2 / pca.t2_limit, spe / pca.spe_limit)
            both = resid / pca.spe_limit + np.clip(share, 0, None) / pca.t2_limit
            contrib[idx] = both.reshape(len(idx), -1, 3).sum(axis=2)
        return score, contrib

    def score(self, w: Windows) -> Scored:
        """Window score: the largest group score; contributions from the deciding group."""
        z = self._z(w)
        results = {g: self._group(g, z, w.regime) for g in self.groups}
        names = list(self.groups)
        stack = np.stack([results[g][0] for g in names], axis=1)
        deciding = stack.argmax(axis=1)
        parts = np.zeros((len(z), len(NUMERIC_TAGS)))
        for k, g in enumerate(names):
            rows = deciding == k
            cols = [TAG[t] for t in self.groups[g]]
            parts[np.ix_(rows, cols)] = results[g][1][rows]
        return Scored(stack.max(axis=1), parts, list(NUMERIC_TAGS))


def pump_state(regime: tuple[int, ...]) -> str:
    """'A', 'B', 'AB' or 'none' from the two pump on/off tags."""
    a, b = regime[PUMP_A] == 1, regime[PUMP_B] == 1
    return {(True, False): "A", (False, True): "B", (True, True): "AB"}.get((a, b), "none")


def _mean(w: Windows, tag: str) -> Floats:
    return w.x[:, TAG[tag], 0]


@dataclass
class Fit:
    """A fault-free fit and the residual scale that goes with it."""

    coef: Floats
    sigma: float

    def z(self, r: float) -> float:
        """Residual beyond one sigma, in sigmas; NaN counts as no evidence."""
        return 0.0 if not np.isfinite(r) else max(0.0, abs(r) - self.sigma) / self.sigma


def _sigma(r: Floats) -> float:
    r = r[np.isfinite(r)]
    return float(median_scale(r, pooled_range(r))[1])


class Residuals:
    """C3: plant mass balance, pump head, discharge loss and receipt-line pressure residuals."""

    NAMES = ["R1_mass_balance", "R2_pump_head", "R3_discharge_loss", "R4_receipt_line"]
    PAIR_NAMES = ["R5_temperature_pair", "R6_pump_pair"]

    def __init__(self, train: Windows, flow_terms: bool = False, pairs: bool = False) -> None:
        self.flow_terms, self.pairs = flow_terms, pairs
        self.fits: dict[tuple[str, str, str], Fit] = {}
        y, design = self._mass(train)
        ok = np.isfinite(y) & np.isfinite(design).all(axis=1)
        coef = np.linalg.lstsq(design[ok], y[ok], rcond=None)[0]
        self.mass = Fit(coef, _sigma(y - design @ coef))
        states = [pump_state(r) for r in train.lineup]
        for kind in ("R2", "R3"):
            for pump in ("A", "B"):
                self._fit_pump(train, states, kind, pump)
        self._fit_receipt(train)
        if pairs:
            self.pair = PairResiduals(train, states)

    def _mass(self, w: Windows) -> tuple[Floats, Floats]:
        """Plant balance target and design: inventory change, intercept, optional flow terms."""
        y = _mean(w, "FT-001") - _mean(w, "FT-201")
        slopes = [w.x[:, TAG[t], 1] * 3600.0 for t in ("LT-101", "LT-102", "LT-103")]
        cols = [*slopes, np.ones(len(w.ids))]
        if self.flow_terms:
            setpoint = np.asarray([cast(float, r[2]) for r in w.regime], dtype=np.float64)
            cols += [_mean(w, "FT-201"), setpoint]
        return y, np.column_stack(cols)

    @staticmethod
    def _pump_xy(w: Windows, kind: str, pump: str) -> tuple[Floats, Floats]:
        q = _mean(w, "FT-201")
        head = _mean(w, f"PT-202{pump}")
        low = _mean(w, "PT-201") if kind == "R2" else _mean(w, "PT-203")
        return q, (head - low)

    def _store(self, key: tuple[str, str, str], q: Floats, y: Floats) -> None:
        ok = np.isfinite(q) & np.isfinite(y)
        coef = fit_quadratic(q[ok], y[ok])
        self.fits[key] = Fit(coef, _sigma(y - predict_quadratic(coef, q)))

    def _fit_pump(self, w: Windows, states: list[str], kind: str, pump: str) -> None:
        q, y = self._pump_xy(w, kind, pump)
        runs = np.asarray([pump in s for s in states], dtype=bool)
        self._store((kind, "*", pump), q[runs], y[runs])
        for state in ("A", "B", "AB"):
            mask = np.asarray([s == state for s in states], dtype=bool) & runs
            if mask.sum() >= MIN_REGIME:
                self._store((kind, state, pump), q[mask], y[mask])

    def _fit_receipt(self, w: Windows) -> None:
        q, y = _mean(w, "FT-001"), _mean(w, "PT-001")
        self._store(("R4", "*", ""), q, y)
        for r in set(w.regime):
            mask = np.asarray([x == r for x in w.regime])
            if mask.sum() >= MIN_REGIME:
                self._store(("R4", str(r), ""), q[mask], y[mask])

    def _pump_z(self, kind: str, state: str, w: Windows) -> Floats:
        out = np.zeros(len(w.ids))
        for pump in ("A", "B"):
            if pump not in state:
                continue
            fit = self.fits.get((kind, state, pump)) or self.fits[(kind, "*", pump)]
            q, y = self._pump_xy(w, kind, pump)
            r = y - predict_quadratic(fit.coef, q)
            out = np.maximum(out, np.asarray([fit.z(float(v)) for v in r]))
        return out

    def score(self, w: Windows) -> Scored:
        """Window score: the largest residual z; contributions per residual group."""
        y, design = self._mass(w)
        r1 = np.asarray([self.mass.z(v) for v in y - design @ self.mass.coef])
        states = np.asarray([pump_state(r) for r in w.lineup])
        parts = np.zeros((len(w.ids), 4))
        parts[:, 0] = r1
        for state in ("A", "B", "AB"):
            rows = states == state
            if rows.any():
                sub = _take(w, rows)
                parts[rows, 1] = self._pump_z("R2", state, sub)
                parts[rows, 2] = self._pump_z("R3", state, sub)
        parts[:, 3] = self._receipt_z(w)
        if not self.pairs:
            return Scored(parts.max(axis=1), parts, list(self.NAMES))
        pair, tags = self.pair.score(w, states)
        both = np.column_stack([parts, pair])
        return Scored(both.max(axis=1), both, [*self.NAMES, *self.PAIR_NAMES], tags)

    def _receipt_z(self, w: Windows) -> Floats:
        out = np.zeros(len(w.ids))
        q, y = _mean(w, "FT-001"), _mean(w, "PT-001")
        for r in set(w.regime):
            idx = np.asarray([i for i, x in enumerate(w.regime) if x == r])
            fit = self.fits.get(("R4", str(r), "")) or self.fits[("R4", "*", "")]
            resid = y[idx] - predict_quadratic(fit.coef, q[idx])
            out[idx] = [fit.z(float(v)) for v in resid]
        return out


class PairResiduals:
    """E3: agreement of related instruments (tank temperatures, the two pump discharges)."""

    TEMPS = ("TT-101", "TT-102", "TT-103")
    MIN_AB = 30

    def __init__(self, train: Windows, states: list[str]) -> None:
        r5 = self._temps(train)
        self.centre5 = np.nanmedian(r5, axis=0)
        self.sigma5 = _sigma((r5 - self.centre5).ravel())
        both = np.asarray([s == "AB" for s in states])
        d = self._discharge(train)[both]
        d = d[np.isfinite(d)]
        self.centre6 = float(np.median(d)) if len(d) >= self.MIN_AB else 0.0
        self.sigma6 = _sigma(d - self.centre6) if len(d) >= self.MIN_AB else float("nan")

    def _temps(self, w: Windows) -> Floats:
        t = np.column_stack([_mean(w, tag) for tag in self.TEMPS])
        return np.asarray(t - np.median(t, axis=1, keepdims=True), dtype=np.float64)

    @staticmethod
    def _discharge(w: Windows) -> Floats:
        return np.asarray(_mean(w, "PT-202A") - _mean(w, "PT-202B"), dtype=np.float64)

    @staticmethod
    def _z(r: Floats, sigma: float) -> Floats:
        z = np.maximum(0.0, np.abs(r) - sigma) / sigma
        return np.asarray(np.nan_to_num(z, nan=0.0), dtype=np.float64)

    def score(self, w: Windows, states: Any) -> tuple[Floats, Floats]:
        """Pair residual values (R5, R6) per window and the per-tag evidence they give."""
        z5 = self._z(self._temps(w) - self.centre5, self.sigma5)
        z6 = np.zeros(len(w.ids))
        if np.isfinite(self.sigma6):
            z6 = self._z(self._discharge(w) - self.centre6, self.sigma6)
            z6 = np.where(np.asarray(states) == "AB", z6, 0.0)
        tags = np.zeros((len(w.ids), len(NUMERIC_TAGS)))
        for k, tag in enumerate(self.TEMPS):
            tags[:, TAG[tag]] = z5[:, k]
        tags[:, TAG["PT-202A"]] = z6
        tags[:, TAG["PT-202B"]] = z6
        return np.column_stack([z5.max(axis=1), z6]), tags


def _take(w: Windows, rows: NDArray[np.bool_]) -> Windows:
    from windows import subset

    return subset(w, rows)


def fuse(train_scores: dict[str, Floats], scores: dict[str, Floats]) -> Scored:
    """C4: minus log10 of the smallest calibrated p-value over the components."""
    names = list(train_scores)
    logs = []
    for name in names:
        ref = np.sort(train_scores[name])
        above = len(ref) - np.searchsorted(ref, scores[name], side="left")
        logs.append(-np.log10((above + 1) / (len(ref) + 1)))
    parts = np.stack(logs, axis=1)
    return Scored(parts.max(axis=1), parts, names)

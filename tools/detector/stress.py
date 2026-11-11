"""Stress test of the pooled C3: missing tags as unknown evidence and noise on the window means.

Models are the fold fits and the validation fit, never refitted. Window inputs are perturbed
and scored again; scores are saved with NaN where a window cannot be scored at all.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import cv
import numpy as np
from candidates import PUMP_A, PUMP_B, Residuals
from fitting import Floats
from systems import fold_map
from windows import NUMERIC_TAGS, Windows, subset

SEED = 20261108
FOLDS = 5
MISSING = (1, 2, 3)
NOISE = (1, 2, 3)
# (tag, statistic index): mean = 0, slope = 1; the two pump tags are read as lineup entries
NUMERIC_INPUTS = (
    ("FT-001", 0), ("FT-201", 0), ("LT-101", 1), ("LT-102", 1), ("LT-103", 1),
    ("PT-001", 0), ("PT-201", 0), ("PT-202A", 0), ("PT-202B", 0), ("PT-203", 0),
)  # fmt: skip
PUMP_POSITIONS = (PUMP_A, PUMP_B)  # entries of the lineup key read as the pump tags
N_INPUTS = len(NUMERIC_INPUTS) + len(PUMP_POSITIONS)


def drop_inputs(w: Windows, rng: np.random.Generator, m: int) -> Windows:
    """Make m of the twelve inputs of every window unknown, chosen at random."""
    chosen = np.argsort(rng.random((len(w.ids), N_INPUTS)), axis=1)[:, :m]
    gone = np.zeros((len(w.ids), N_INPUTS), dtype=bool)
    np.put_along_axis(gone, chosen, True, axis=1)
    x = w.x.copy()
    for j, (tag, stat) in enumerate(NUMERIC_INPUTS):
        x[gone[:, j], NUMERIC_TAGS.index(tag), stat] = np.nan
    lineup = []
    for i, key in enumerate(w.lineup):
        row = list(key)
        for j, pos in enumerate(PUMP_POSITIONS):
            if gone[i, len(NUMERIC_INPUTS) + j]:
                row[pos] = -1
        lineup.append(tuple(row))
    return replace(w, x=x, lineup=lineup)


def noise_scales(model: Residuals) -> Floats:
    """Noise sd per numeric input that alone moves its residual by one fault-free scale."""
    f = model.fits
    s1, areas = model.mass.sigma, model.mass.coef[:3]
    r2 = [f[("R2", "*", "A")].sigma, f[("R2", "*", "B")].sigma]
    r3 = [f[("R3", "*", "A")].sigma, f[("R3", "*", "B")].sigma]
    by_tag = {
        "FT-001": s1, "FT-201": s1, "PT-001": f[("R4", "*", "")].sigma,
        "LT-101": s1 / (3600.0 * areas[0]), "LT-102": s1 / (3600.0 * areas[1]),
        "LT-103": s1 / (3600.0 * areas[2]), "PT-202A": r2[0], "PT-202B": r2[1],
        "PT-201": float(np.mean(r2)), "PT-203": float(np.mean(r3)),
    }  # fmt: skip
    return np.asarray([by_tag[tag] for tag, _ in NUMERIC_INPUTS])


def add_noise(w: Windows, rng: np.random.Generator, scales: Floats, k: int) -> Windows:
    """Add independent Gaussian noise of k times the scale to the ten numeric inputs."""
    x = w.x.copy()
    for j, (tag, stat) in enumerate(NUMERIC_INPUTS):
        x[:, NUMERIC_TAGS.index(tag), stat] += rng.normal(0.0, k * scales[j], len(w.ids))
    return replace(w, x=x)


def score_unknown(model: Residuals, w: Windows) -> Floats:
    """Scores with unavailable residuals unknown; NaN where no residual is available."""
    model.unknown = float("nan")
    try:
        return model.score(w).scores
    finally:
        model.unknown = 0.0


def settings(model: Residuals, w: Windows, fold: int) -> dict[str, Floats]:
    """Clean scores and the six perturbed settings for one set of windows."""
    out = {"clean": model.score(w).scores}
    for m in MISSING:
        rng = np.random.default_rng([SEED, 10 + m, fold])
        out[f"missing_{m}"] = score_unknown(model, drop_inputs(w, rng, m))
    scales = noise_scales(model)
    for k in NOISE:
        rng = np.random.default_rng([SEED, 20 + k, fold])
        out[f"noise_{k}"] = score_unknown(model, add_noise(w, rng, scales, k))
    return out


def run(rel: Path, work: Path) -> None:
    """Out of fold (five folds) and validation; writes one array file."""
    train, val, _ = cv.load_conditioned(rel)
    units = fold_map(train.unit, FOLDS)
    which = np.asarray([units[u] for u in train.unit])
    store: dict[str, Floats] = {}
    for k in range(FOLDS):
        held = which == k
        fit_all = subset(train, ~held)
        model = Residuals(subset(fit_all, fit_all.faulty == 0), pooled_r4=True)
        for name, s in settings(model, subset(train, held), k).items():
            cv._place(store, f"oof_{name}", s, np.flatnonzero(held), len(which))
    model = Residuals(subset(train, train.faulty == 0), pooled_r4=True)
    for name, s in settings(model, val, FOLDS).items():
        store[f"val_{name}"] = s
    work.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(work / "stress.npz", **store)  # type: ignore[arg-type]

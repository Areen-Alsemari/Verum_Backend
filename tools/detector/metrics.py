"""Ranking metrics, episode-level bootstrap, cross-fitted thresholds and the shuffle control.

All functions take plain arrays. Labels are 1 for a faulty window and 0 for a fault-free one.
Ties in scores are handled by average ranks and by grouping equal scores in the precision curve.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray

Floats = NDArray[np.float64]
Ints = NDArray[np.intp]
Metric = Callable[[Ints], float]


def average_ranks(x: Floats) -> Floats:
    """Ranks starting at 1, ties receiving the mean of their ranks."""
    _, inverse, counts = np.unique(x, return_inverse=True, return_counts=True)
    ends = np.cumsum(counts)
    return np.asarray(ends - (counts - 1) / 2.0, dtype=np.float64)[inverse]


def auroc(scores: Floats, labels: Ints) -> float:
    """Area under the ROC curve; NaN when one class is missing."""
    pos = int(np.sum(labels == 1))
    neg = int(len(labels) - pos)
    if pos == 0 or neg == 0:
        return float("nan")
    ranks = average_ranks(scores)
    return float((ranks[labels == 1].sum() - pos * (pos + 1) / 2.0) / (pos * neg))


def average_precision(scores: Floats, labels: Ints) -> float:
    """Average precision with tied scores grouped into one step of the curve."""
    pos = int(np.sum(labels == 1))
    if pos == 0:
        return float("nan")
    order = np.argsort(-scores, kind="mergesort")
    s, y = scores[order], labels[order]
    ends = np.r_[np.flatnonzero(np.diff(s) != 0), len(s) - 1]
    tp = np.cumsum(y == 1)[ends]
    seen = ends + 1
    recall = tp / pos
    gain = np.diff(np.r_[0.0, recall])
    return float(np.sum(gain * (tp / seen)))


def matched_stage_auroc(scores: Floats, labels: Ints, stage: Ints) -> float:
    """AUROC inside each stage that holds both classes, weighted by the number of pairs."""
    total = 0.0
    weight = 0.0
    for value in np.unique(stage):
        m = stage == value
        pos = int(np.sum(labels[m] == 1))
        neg = int(m.sum() - pos)
        if pos and neg:
            total += auroc(scores[m], labels[m]) * pos * neg
            weight += pos * neg
    return float(total / weight) if weight else float("nan")


def episode_groups(episodes: list[str]) -> list[Ints]:
    """Window indices grouped by episode, in sorted episode order."""
    order: dict[str, list[int]] = {}
    for i, name in enumerate(episodes):
        order.setdefault(name, []).append(i)
    return [np.asarray(order[k], dtype=np.intp) for k in sorted(order)]


def make_resamples(groups: list[Ints], resamples: int, seed: int) -> list[Ints]:
    """Index arrays of whole-episode resamples, shared by every metric and candidate."""
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(resamples):
        pick = rng.integers(0, len(groups), len(groups))
        out.append(np.concatenate([groups[i] for i in pick]))
    return out


def interval(
    metric: Metric, point_index: Ints, resamples: list[Ints]
) -> tuple[float, float, float]:
    """Point value and 95% percentile interval of a metric over shared resamples."""
    values = np.asarray([metric(idx) for idx in resamples])
    lo, hi = np.nanpercentile(values, [2.5, 97.5])
    return float(metric(point_index)), float(lo), float(hi)


def bootstrap(
    metric: Metric, groups: list[Ints], resamples: int, seed: int
) -> tuple[float, float, float]:
    """Point value and 95% percentile interval, resampling whole episodes."""
    return interval(metric, np.concatenate(groups), make_resamples(groups, resamples, seed))


def fold_of(episode_id: str) -> int:
    """Fold 0 or 1 from the parity of the identifier read as hexadecimal."""
    return int(episode_id.split("-")[1], 16) % 2


def cross_fit_alarms(scores: Floats, labels: Ints, folds: Ints, far: float) -> NDArray[np.bool_]:
    """Alarm when the score exceeds the far-quantile of fault-free scores of the other fold."""
    alarms = np.zeros(len(scores), dtype=bool)
    for fold in (0, 1):
        reference = scores[(folds != fold) & (labels == 0)]
        threshold = np.percentile(reference, 100.0 * (1.0 - far))
        alarms[folds == fold] = scores[folds == fold] > threshold
    return alarms


def rate(flags: NDArray[np.bool_], subset: NDArray[np.bool_]) -> tuple[int, int]:
    """Number of flagged windows and size of the subset."""
    return int(np.sum(flags & subset)), int(np.sum(subset))


def shuffle_control(
    scores: Floats, labels: Ints, stage: Ints, permutations: int, seed: int
) -> dict[str, tuple[float, float, float]]:
    """Mean and 2.5%, 97.5% range of AP, AUROC and matched-stage AUROC under shuffled labels."""
    rng = np.random.default_rng(seed)
    out: dict[str, list[float]] = {"ap": [], "auroc": [], "matched": []}
    for _ in range(permutations):
        shuffled = rng.permutation(labels)
        within = labels.copy()
        for value in np.unique(stage):
            m = np.flatnonzero(stage == value)
            within[m] = rng.permutation(labels[m])
        out["ap"].append(average_precision(scores, shuffled))
        out["auroc"].append(auroc(scores, shuffled))
        out["matched"].append(matched_stage_auroc(scores, within, stage))
    return {k: summarise(np.asarray(v)) for k, v in out.items()}


def summarise(values: Floats) -> tuple[float, float, float]:
    """Mean and the 2.5% and 97.5% percentiles, ignoring NaN."""
    lo, hi = np.nanpercentile(values, [2.5, 97.5])
    return float(np.nanmean(values)), float(lo), float(hi)

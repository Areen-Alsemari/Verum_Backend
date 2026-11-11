"""Alarm policies (k of the last n windows) on a window score, with episode-level metrics.

A policy is alarming at a window when at least k of the windows at positions t-n+1 to t that
exist in the episode have a score above the threshold. Thresholds are calibrated on the scores
of fault-free episodes so that at most a stated share of them ever alarm. Rates carry 95%
bootstrap intervals over whole episodes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import metrics as m
import numpy as np
from numpy.typing import NDArray

POLICIES = ((1, 1), (2, 3), (3, 5))
EPISODE_TARGET = 0.05
WINDOWS_PER_DAY = 288.0
Floats = NDArray[np.float64]
Bools = NDArray[np.bool_]


@dataclass
class Episodes:
    """Windows of one set grouped by episode, with labels and onsets."""

    scores: Floats
    y: m.Ints
    stage: m.Ints
    cutoff: Floats
    kind: NDArray[np.str_]
    eid: m.Ints
    order: list[m.Ints]
    onset: Floats
    ep_faulty: Bools
    ep_type: list[str]
    ep_fold: m.Ints


def build(d: Any, meta: dict[str, Any], scores: Floats, fold: m.Ints | None = None) -> Episodes:
    """Group windows by episode in position order."""
    names = sorted(set(meta["episodes"]))
    where = {n: i for i, n in enumerate(names)}
    eid = np.asarray([where[e] for e in meta["episodes"]], dtype=np.intp)
    stage, y = d["stage"].astype(np.intp), d["faulty"].astype(np.intp)
    kind, onset_w = np.asarray(meta["kind"]), d["onset_s"]
    order, faulty, types, onset = [], [], [], []
    for i in range(len(names)):
        rows = np.flatnonzero(eid == i)
        rows = rows[np.argsort(stage[rows])]
        bad = rows[y[rows] == 1]
        order.append(rows)
        faulty.append(len(bad) > 0)
        types.append(str(kind[bad[0]]) if len(bad) else "")
        onset.append(float(np.nanmin(onset_w[rows])) if len(bad) else float("nan"))
    ep_fold = np.zeros(len(names), dtype=np.intp) if fold is None else fold[[o[0] for o in order]]
    return Episodes(
        scores, y, stage, d["cutoff"], kind, eid, order, np.asarray(onset),
        np.asarray(faulty, dtype=bool), types, ep_fold,
    )  # fmt: skip


def alarm_state(
    e: Episodes, thr: float, k: int, n: int, episodes: list[int] | None = None
) -> Bools:
    """Policy state at every window of the given episodes (all when None)."""
    state = np.zeros(len(e.scores), dtype=bool)
    for i in range(len(e.order)) if episodes is None else episodes:
        idx = e.order[i]
        s, over = e.stage[idx], e.scores[idx] > thr
        for j in range(len(idx)):
            state[idx[j]] = over[(s > s[j] - n) & (s <= s[j])].sum() >= k
    return state


def share_alarmed(e: Episodes, thr: float, k: int, n: int, episodes: list[int]) -> float:
    """Share of the given episodes with the policy alarming at any window."""
    state = alarm_state(e, thr, k, n, episodes)
    return float(np.mean([state[e.order[i]].any() for i in episodes]))


def calibrate(e: Episodes, episodes: list[int], k: int, n: int, target: float) -> float:
    """Smallest candidate threshold whose episode alarm share is at most the target."""
    pool = np.unique(np.concatenate([e.scores[e.order[i]] for i in episodes]))
    cand = np.append(pool, pool[-1] + 1.0)
    lo, hi = 0, len(cand) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if share_alarmed(e, float(cand[mid]), k, n, episodes) <= target:
            hi = mid
        else:
            lo = mid + 1
    return float(cand[lo])

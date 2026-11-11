"""One detector system: components fitted on a fault-free set, scored on other windows, fused.

A system is the fusion of C1n (per-tag baseline without CUSUM), C2a and C2b (PCA), and C3
(topology residuals), with the enhancements named in its spec. Calibration of the fusion is
in-sample (the scores of the fit windows) or out-of-sample (inner grouped cross-fitting).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from candidates import GROUPS, PcaMonitor, PerTag, Residuals, Scored, fuse
from fitting import Floats, fit_baseline, fit_regression_baseline
from windows import NUMERIC_TAGS, Windows, subset

INNER_FOLDS = 4


@dataclass(frozen=True)
class Spec:
    """Which enhancements a system carries (section 12.3 of the plan)."""

    e1: bool = False
    e2: bool = False
    e3: bool = False
    e4: bool = False
    pooled_r4: bool = False

    @property
    def label(self) -> str:
        """Short name, for example 'B0' or 'E1+E3'."""
        on = [
            n for n, v in (("E1", self.e1), ("E2", self.e2), ("E3", self.e3), ("E4", self.e4)) if v
        ]
        return "+".join(on) if on else "B0"


def fold_map(units: list[tuple[str, str, float]], k: int) -> dict[tuple[str, str, float], int]:
    """Unit i of the sorted unit list goes to fold i mod k."""
    return {u: i % k for i, u in enumerate(sorted(set(units)))}


class Components:
    """C1n, C2a, C2b and C3 fitted on one fault-free set."""

    def __init__(self, fit: Windows, spec: Spec) -> None:
        base = (fit_regression_baseline if spec.e1 else fit_baseline)(fit.x, fit.regime)
        self.c1 = PerTag(fit, base)
        self.c2a = PcaMonitor(fit, base, {"all": list(NUMERIC_TAGS)})
        self.c2b = PcaMonitor(fit, base, GROUPS)
        self.c3 = Residuals(fit, flow_terms=spec.e2, pairs=spec.e3, pooled_r4=spec.pooled_r4)

    def score(self, w: Windows) -> dict[str, Scored]:
        """Scores of every component for the given windows."""
        return {
            "C1n": self.c1.score(w, None), "C2a": self.c2a.score(w),
            "C2b": self.c2b.score(w), "C3": self.c3.score(w),
        }  # fmt: skip


def reference(fit: Windows, spec: Spec) -> dict[str, Floats]:
    """Fault-free reference scores for the p-values: in-sample, or inner out-of-fold."""
    if not spec.e4:
        return {k: v.scores for k, v in Components(fit, spec).score(fit).items()}
    folds = fold_map(fit.unit, INNER_FOLDS)
    which = np.asarray([folds[u] for u in fit.unit])
    out: dict[str, Floats] = {}
    for k in range(INNER_FOLDS):
        held = which == k
        got = Components(subset(fit, ~held), spec).score(subset(fit, held))
        for name, scored in got.items():
            out.setdefault(name, np.full(len(fit.ids), np.nan))[held] = scored.scores
    return out


@dataclass
class Result:
    """Scores of a system for a set of windows."""

    scores: dict[str, Floats]
    parts: dict[str, Floats]
    names: dict[str, list[str]]
    tags: Floats


def score_system(fit: Windows, apply: Windows, spec: Spec) -> Result:
    """Fit on the fault-free set, score the other windows, fuse with the chosen calibration."""
    got = Components(fit, spec).score(apply)
    fused = fuse(reference(fit, spec), {k: v.scores for k, v in got.items()})
    scores = {k: v.scores for k, v in got.items()} | {"C4": fused.scores}
    parts = {k: v.parts for k, v in got.items()} | {"C4": fused.parts}
    names = {k: v.names for k, v in got.items()} | {"C4": fused.names}
    tags = np.zeros((len(apply.ids), len(NUMERIC_TAGS)))
    for scored in got.values():
        if scored.tags is not None:
            tags = np.maximum(tags, scored.tags)
    return Result(scores, parts, names, tags)

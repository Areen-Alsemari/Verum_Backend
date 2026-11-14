"""Residual signature of each fault type for the four topology residuals of C3.

For every fault type: the mean share of each residual in the score, the fraction of windows in
which it is the largest, and the fraction in which it exceeds its own threshold, the 95th
percentile of that residual on fault-free windows the model did not see. Descriptive only.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray
from windows import FAULT_TYPES

NAMES = ["R1_mass_balance", "R2_pump_head", "R3_discharge_loss", "R4_receipt_line"]
Floats = NDArray[np.float64]
DISTINCT_MIN, SECOND_RATIO, NONE_MAX = 0.30, 2.0, 0.15


def fold_thresholds(parts: Floats, y: NDArray[np.intp], fold: NDArray[np.intp]) -> Floats:
    """Per-window thresholds: 95th percentile of fault-free windows of the other folds."""
    out = np.zeros_like(parts)
    for f in np.unique(fold):
        sel = (fold != f) & (y == 0)
        out[fold == f] = np.percentile(parts[sel], 95, axis=0)
    return out


def reference_thresholds(parts: Floats, y: NDArray[np.intp], n: int) -> Floats:
    """The same percentile from reference fault-free windows, repeated for n windows."""
    return np.tile(np.percentile(parts[y == 0], 95, axis=0), (n, 1))


def _row(parts: Floats, thr: Floats) -> dict[str, Any]:
    total = parts.sum(axis=1)
    live = total > 0
    share = np.where(live[:, None], parts / np.maximum(total, 1e-12)[:, None], 0.0)
    top = np.argmax(parts, axis=1)
    return {
        "n": len(parts),
        "share": [round(float(v), 4) for v in share.mean(axis=0)],
        "top": [round(float((live & (top == j)).mean()), 4) for j in range(parts.shape[1])],
        "none": round(float((~live).mean()), 4),
        "exceed": [round(float((parts[:, j] > thr[:, j]).mean()), 4) for j in range(4)],
    }


def matrix(
    parts: Floats, thr: Floats, kind: NDArray[np.str_], y: NDArray[np.intp]
) -> dict[str, Any]:
    """One row per fault type, plus fault-free windows as the reference row."""
    out = {t: _row(parts[kind == t], thr[kind == t]) for t in FAULT_TYPES if (kind == t).any()}
    out["fault-free"] = _row(parts[y == 0], thr[y == 0])
    return out


def classify(exceed: list[float]) -> str:
    """'distinct R<j>', 'none' or 'shared' by the rule fixed in the plan."""
    order = np.argsort(exceed)[::-1]
    top, second = exceed[order[0]], exceed[order[1]]
    if top < NONE_MAX:
        return "none"
    if top >= DISTINCT_MIN and top >= SECOND_RATIO * second:
        return f"distinct R{int(order[0]) + 1}"
    return "shared"


def agreement(oof: dict[str, Any], val: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Classification out of fold and on validation, and the verdict when they agree."""
    out = {}
    for t in FAULT_TYPES:
        if t not in oof or t not in val:
            continue
        a, b = classify(oof[t]["exceed"]), classify(val[t]["exceed"])
        out[t] = {"oof": a, "val": b, "verdict": a if a == b else "disagree"}
    return out

"""Metrics, intervals, cross-fitted alarms and controls for every candidate and baseline.

Reads only the work folder written by the scoring stage. The stop rule of the plan is
evaluated at the end and written next to the numbers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import metrics as m
import numpy as np
from numpy.typing import NDArray
from windows import FAULT_TYPES, NUMERIC_TAGS, STATS

SEED = 20261108
RESAMPLES = 1000
PERMUTATIONS = 200
FAR_TARGET = 0.05
CANDIDATES = ["C1", "C2a", "C2b", "C3", "C4"]
SENSITIVITY = ["C1s", "C2as", "C2bs", "C4s"]
MODELS = ["always_flag", "random", "C0", *CANDIDATES, *SENSITIVITY]
COLUMNS_USED = {
    "C3": ["FT-001:mean", "FT-201:mean", "LT-101:slope_per_s", "LT-102:slope_per_s",
           "LT-103:slope_per_s", "PT-001:mean", "PT-201:mean", "PT-202A:mean",
           "PT-202B:mean", "PT-203:mean"],
}  # fmt: skip
Floats = NDArray[np.float64]


def _ci(point: tuple[float, float, float]) -> list[float]:
    return [round(v, 4) for v in point]


def _discrimination(
    s: Floats, y: m.Ints, stage: m.Ints, idx: m.Ints, res: list[m.Ints]
) -> dict[str, list[float]]:
    return {
        "ap": _ci(m.interval(lambda i: m.average_precision(s[i], y[i]), idx, res)),
        "auroc": _ci(m.interval(lambda i: m.auroc(s[i], y[i]), idx, res)),
        "matched_auroc": _ci(
            m.interval(lambda i: m.matched_stage_auroc(s[i], y[i], stage[i]), idx, res)
        ),
    }


def _alarm_rates(
    alarms: NDArray[np.bool_], y: m.Ints, kind: NDArray[np.str_], idx: m.Ints, res: list[m.Ints]
) -> dict[str, Any]:
    def far(i: m.Ints) -> float:
        sel = y[i] == 0
        return float(alarms[i][sel].mean()) if sel.any() else float("nan")

    out: dict[str, Any] = {"far": _ci(m.interval(far, idx, res))}
    recall = {}
    for t in FAULT_TYPES:

        def rec(i: m.Ints, t: str = t) -> float:
            sel = kind[i] == t
            return float(alarms[i][sel].mean()) if sel.any() else float("nan")

        recall[t] = {"n": int((kind == t).sum()), "recall": _ci(m.interval(rec, idx, res))}
    out["recall_by_type"] = recall
    out["recall_all"] = _ci(m.interval(lambda i: float(alarms[i][y[i] == 1].mean()), idx, res))
    return out


def _top_contributors(parts: Floats, names: list[str], y: m.Ints) -> list[list[Any]]:
    share = parts / np.maximum(parts.sum(axis=1, keepdims=True), 1e-12)
    mean = share[y == 1].mean(axis=0)
    order = np.argsort(-mean)[:10]
    return [[names[i], round(float(mean[i]), 4)] for i in order]


def constant_columns(x: Floats, cusum: Floats, y: m.Ints) -> dict[str, list[str]]:
    """Columns with fewer than 3 distinct values or zero variance across faulty windows."""
    flagged = []
    faulty = y == 1
    for j, tag in enumerate(NUMERIC_TAGS):
        for k, stat in enumerate(STATS):
            col = x[faulty, j, k]
            col = col[np.isfinite(col)]
            if len(np.unique(col)) < 3 or float(col.std()) == 0.0:
                flagged.append(f"{tag}:{stat}")
        c = cusum[faulty, j]
        c = c[np.isfinite(c)]
        if len(np.unique(c)) < 3 or float(c.std()) == 0.0:
            flagged.append(f"{tag}:cusum")
    return {"flagged_columns": flagged}


def stop_rule(results: dict[str, Any], prevalence: float) -> dict[str, Any]:
    """Which candidates pass: AP lower bound above prevalence, matched AUROC bound above 0.55."""
    rows = {}
    for name in CANDIDATES:
        disc = results[name]["discrimination"]
        rows[name] = {
            "ap_lower_above_prevalence": bool(disc["ap"][1] > prevalence),
            "matched_lower_above_0.55": bool(disc["matched_auroc"][1] > 0.55),
        }
    passed = [n for n, v in rows.items() if all(v.values())]
    return {"by_candidate": rows, "passed": passed, "no_candidate_beat_chance": not passed}


class Context:
    """Labels, stages, folds and shared resamples of the validation windows."""

    def __init__(self, d: Any, meta: dict[str, Any]) -> None:
        self.y = d["faulty"].astype(np.intp)
        self.stage = d["stage"].astype(np.intp)
        self.kind = np.asarray(meta["kind"])
        self.folds = np.asarray([m.fold_of(e) for e in meta["episodes"]], dtype=np.intp)
        groups = m.episode_groups(meta["episodes"])
        self.res = m.make_resamples(groups, RESAMPLES, SEED)
        self.idx = np.concatenate(groups)


def evaluate_model(name: str, d: Any, meta: dict[str, Any], c: Context) -> dict[str, Any]:
    """Discrimination, alarm rates, shuffle control and top contributors for one score."""
    s = d[f"score_{name}"].astype(np.float64)
    alarms = m.cross_fit_alarms(s, c.y, c.folds, FAR_TARGET)
    shuffle = m.shuffle_control(s, c.y, c.stage, PERMUTATIONS, SEED)
    r: dict[str, Any] = {
        "discrimination": _discrimination(s, c.y, c.stage, c.idx, c.res),
        "alarms_at_5pct_far": _alarm_rates(alarms, c.y, c.kind, c.idx, c.res),
        "shuffle": {k: [round(v, 4) for v in t] for k, t in shuffle.items()},
    }
    if f"parts_{name}" in d:
        r["top_contributors"] = _top_contributors(d[f"parts_{name}"], meta["part_names"][name], c.y)
    return r


def run(work: Path, out: Path) -> dict[str, Any]:
    """Evaluate everything in the work folder and write the results file."""
    d = np.load(work / "scores.npz")
    meta = json.loads((work / "meta.json").read_text())
    c = Context(d, meta)
    results: dict[str, Any] = {
        "prevalence": float(c.y.mean()), "windows": len(c.y), "faulty": int(c.y.sum()),
    }  # fmt: skip
    for name in MODELS:
        results[name] = evaluate_model(name, d, meta, c)
    shipped = d["score_C0"] >= meta["c0_threshold"]
    results["C0_shipped_threshold"] = {
        "threshold": meta["c0_threshold"], "far": float(shipped[c.y == 0].mean()),
        "recall": float(shipped[c.y == 1].mean()), "flagged_share": float(shipped.mean()),
    }  # fmt: skip
    results["constant_columns"] = constant_columns(d["x"], d["cusum"], c.y)
    results["stop_rule"] = stop_rule(results, results["prevalence"])
    out.write_text(json.dumps(results, indent=1))
    return results

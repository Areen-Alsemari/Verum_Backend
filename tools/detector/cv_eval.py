"""Metrics, delay, localisation, controls and paired differences for the grouped-CV systems.

Reads the arrays and metadata written by the cv stage. Intervals are 95% bootstrap over whole
episodes with the seed of the plan, and paired differences use the same resamples.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import evaluate as ev
import metrics as m
import numpy as np
from diagnostics import placebo
from numpy.typing import NDArray
from windows import NUMERIC_TAGS, STATS

WINDOWS_PER_DAY = 288.0
Floats = NDArray[np.float64]


def detection_delay(
    alarms: NDArray[np.bool_], y: m.Ints, episodes: list[str], cutoff: Floats, onset: Floats
) -> dict[str, Any]:
    """Seconds from the earliest onset to the cutoff of the first alarmed faulty window."""
    delays, never = [], 0
    for ep in sorted(set(episodes)):
        idx = np.flatnonzero((np.asarray(episodes) == ep) & (y == 1))
        if len(idx) == 0:
            continue
        hit = idx[alarms[idx]]
        if len(hit) == 0:
            never += 1
        else:
            first = hit[np.argmin(cutoff[hit])]
            delays.append(float(cutoff[first] - onset[first]))
    q = np.percentile(delays, [25, 50, 75]).tolist() if delays else [float("nan")] * 3
    return {"episodes": len(delays) + never, "never_alarmed": never,
            "quartiles_s": [round(v, 1) for v in q]}  # fmt: skip


def tag_ranks(tags: Floats, true_tag: list[str]) -> Floats:
    """Rank of the faulty tag among the 14 (1 = strictly highest; ties count against it)."""
    out = np.full(len(true_tag), np.nan)
    for i, name in enumerate(true_tag):
        if name:
            value = tags[i, NUMERIC_TAGS.index(name)]
            out[i] = float((tags[i] >= value).sum())
    return out


def localisation(ranks: Floats, idx: m.Ints, res: list[m.Ints]) -> dict[str, Any]:
    """Top-1 and top-3 accuracy with bootstrap intervals, over scored windows."""
    scored = np.isfinite(ranks)

    def acc(k: int) -> Any:
        def f(i: m.Ints) -> float:
            sel = scored[i]
            return float((ranks[i][sel] <= k).mean()) if sel.any() else float("nan")

        return f

    return {
        "windows": int(scored.sum()),
        "top1": [round(v, 4) for v in m.interval(acc(1), idx, res)],
        "top3": [round(v, 4) for v in m.interval(acc(3), idx, res)],
    }


def paired(a: Floats, b: Floats, c: ev.Context) -> dict[str, list[float]]:
    """Differences a minus b of AP and matched-stage AUROC on shared resamples."""
    ap = m.interval(
        lambda i: m.average_precision(a[i], c.y[i]) - m.average_precision(b[i], c.y[i]),
        c.idx,
        c.res,
    )
    ma = m.interval(
        lambda i: (
            m.matched_stage_auroc(a[i], c.y[i], c.stage[i])
            - m.matched_stage_auroc(b[i], c.y[i], c.stage[i])
        ),
        c.idx,
        c.res,
    )
    return {"ap": [round(v, 4) for v in ap], "matched_auroc": [round(v, 4) for v in ma]}


def constant_columns(x: Floats, y: m.Ints) -> list[str]:
    """Summary columns with fewer than 3 distinct values or zero variance across faulty windows."""
    flagged = []
    for j, tag in enumerate(NUMERIC_TAGS):
        for k, stat in enumerate(STATS):
            col = x[y == 1, j, k]
            col = col[np.isfinite(col)]
            if len(np.unique(col)) < 3 or float(col.std()) == 0.0:
                flagged.append(f"{tag}:{stat}")
    return flagged


def condition_inputs(regimes: list[list[Any]]) -> dict[str, int]:
    """Distinct values of each set-condition input over all windows (the inputs of E1)."""
    names = ("atmosphere", "temperature_c", "setpoint_m3h")
    return {n: len({str(r[k]) for r in regimes}) for k, n in enumerate(names)}


def model_extras(
    name: str, d: Any, meta: dict[str, Any], c: ev.Context, later: m.Ints, groups: list[m.Ints]
) -> dict[str, Any]:
    """False alarms per day, delay, localisation and placebo for one score."""
    s = d[f"score_{name}"].astype(np.float64)
    alarms = m.cross_fit_alarms(s, c.y, c.folds, ev.FAR_TARGET)
    far = float(alarms[c.y == 0].mean())
    out: dict[str, Any] = {"false_alarms_per_day": round(far * WINDOWS_PER_DAY, 2)}
    out["delay"] = detection_delay(alarms, c.y, meta["episodes"], d["cutoff"], d["onset_s"])
    out["placebo"] = [round(v, 4) for v in placebo(s, later, c.stage, groups)]
    return out


def evaluate_set(work: Path, tag: str, names: list[str]) -> dict[str, Any]:
    """Everything for one evaluation set ('oof' or 'val')."""
    d = np.load(work / f"{tag}.npz")
    meta = json.loads((work / f"{tag}_meta.json").read_text())
    c = ev.Context(d, meta)
    eps = np.asarray(meta["episodes"])
    later = np.isin(eps, eps[c.y == 1]).astype(np.intp)
    groups = m.episode_groups(meta["episodes"])
    out: dict[str, Any] = {"prevalence": float(c.y.mean()), "windows": len(c.y)}
    for name in names:
        r = ev.evaluate_model(name, d, meta, c)
        r.update(model_extras(name, d, meta, c, later, groups))
        out[name] = r
    ranks = tag_ranks(d["tags"], meta["true_tag"])
    out["localisation"] = localisation(ranks, c.idx, c.res)
    out["constant_columns"] = constant_columns(d["x"], c.y)
    out["condition_inputs"] = condition_inputs(meta["regimes"])
    return out


def compare_systems(prev: Path, new: Path, tag: str, name: str = "C4") -> dict[str, Any]:
    """Paired differences new minus previous for one score of two systems on the same windows."""
    d0, d1 = np.load(prev / f"{tag}.npz"), np.load(new / f"{tag}.npz")
    meta = json.loads((prev / f"{tag}_meta.json").read_text())
    c = ev.Context(d0, meta)
    return paired(d1[f"score_{name}"].astype(np.float64), d0[f"score_{name}"].astype(np.float64), c)


def keep_rule(diff: dict[str, list[float]]) -> bool:
    """Keep only if the lower bounds of both paired differences are above zero."""
    return bool(diff["ap"][1] > 0.0 and diff["matched_auroc"][1] > 0.0)


def run(work: Path, out: Path) -> dict[str, Any]:
    """Evaluate both sets of a cv work folder and write the results."""
    names = ["C1n", "C2a", "C2b", "C3", "C4", "prior"]
    res = {tag: evaluate_set(work, tag, names) for tag in ("oof", "val")}
    out.write_text(json.dumps(res, indent=1))
    return res

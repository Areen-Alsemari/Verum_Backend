"""Post-hoc controls added after the first results were seen, to test for episode-type artefacts.

They were not part of the pre-registered plan and take no part in the stop rule. The placebo
test compares windows before any fault can occur (positions 1 to 5) from episodes that later
contain a fault with windows from episodes that never do. A detector that separates them is
reading the kind of episode, not a fault.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import guard
import metrics as m
import numpy as np
from evaluate import MODELS, RESAMPLES, SEED
from numpy.typing import NDArray
from windows import FAULT_TYPES, NUMERIC_TAGS, load_split

LEVEL_COLUMN = NUMERIC_TAGS.index("TT-001")


def _ci(point: tuple[float, float, float]) -> list[float]:
    return [round(v, 4) for v in point]


def placebo(
    s: NDArray[np.float64],
    later_fault: m.Ints,
    stage: m.Ints,
    groups: list[m.Ints],
) -> list[float]:
    """Matched-stage AUROC, early windows only, label = the episode contains a fault later."""
    early = np.flatnonzero(stage <= 5)
    index = {int(i): k for k, i in enumerate(early)}
    sub_groups = [
        np.asarray([index[int(i)] for i in g if int(i) in index], dtype=np.intp) for g in groups
    ]
    sub_groups = [g for g in sub_groups if len(g)]
    sub_res = m.make_resamples(sub_groups, RESAMPLES, SEED)
    se, sl, st = s[early], later_fault[early], stage[early]
    point = np.arange(len(early), dtype=np.intp)
    return _ci(m.interval(lambda i: m.matched_stage_auroc(se[i], sl[i], st[i]), point, sub_res))


def subset_metrics(
    s: NDArray[np.float64], y: m.Ints, stage: m.Ints, mask: Any, episodes: list[str] | None = None
) -> dict[str, Any]:
    """AP and matched-stage AUROC on a subset; with episodes also their 95% intervals."""
    out: dict[str, Any] = {
        "n": int(mask.sum()), "faulty": int(y[mask].sum()),
        "ap": round(m.average_precision(s[mask], y[mask]), 4),
        "matched_auroc": round(m.matched_stage_auroc(s[mask], y[mask], stage[mask]), 4),
    }  # fmt: skip
    if episodes is not None:
        sel = np.flatnonzero(mask)
        ss, ys, st = s[sel], y[sel], stage[sel]
        groups = m.episode_groups([episodes[i] for i in sel])
        res = m.make_resamples(groups, RESAMPLES, SEED)
        point = np.arange(len(sel), dtype=np.intp)
        out["ap_ci"] = _ci(m.interval(lambda i: m.average_precision(ss[i], ys[i]), point, res))
        out["matched_ci"] = _ci(
            m.interval(lambda i: m.matched_stage_auroc(ss[i], ys[i], st[i]), point, res)
        )
    return out


def seen_recall(alarms: Any, kind: Any, seen: Any) -> dict[str, list[int]]:
    """Recall by fault type among faulty windows in seen regimes: number alarmed and total."""
    out = {}
    for t in FAULT_TYPES:
        sel = (kind == t) & seen
        out[t] = [int(alarms[sel].sum()), int(sel.sum())]
    return out


def run(rel: Path, work: Path, out: Path) -> dict[str, Any]:
    """Placebo, regime and temperature controls for every score in the work folder."""
    guard.install()
    d = np.load(work / "scores.npz")
    meta = json.loads((work / "meta.json").read_text())
    val, train = load_split(rel, "validation"), load_split(rel, "train")
    guard.ALLOWED_EPISODES.update(val.episodes)
    y, stage = d["faulty"].astype(np.intp), d["stage"].astype(np.intp)
    eps = np.asarray(meta["episodes"])
    fault_eps = set(eps[y == 1])
    later = np.asarray([e in fault_eps for e in meta["episodes"]], dtype=np.intp)
    ff = Counter(r for r, f in zip(train.regime, train.faulty, strict=True) if f == 0)
    seen = np.asarray([ff.get(r, 0) >= 200 for r in val.regime], dtype=bool)
    temp = np.round(d["x"][:, LEVEL_COLUMN, 0] / 5.0) * 5.0
    groups = m.episode_groups(meta["episodes"])
    res: dict[str, Any] = {
        "placebo": {},
        "seen_regime": {},
        "by_temperature": {},
        "seen_recall": {},
    }
    folds = np.asarray([m.fold_of(e) for e in meta["episodes"]], dtype=np.intp)
    kind = np.asarray(meta["kind"])
    res["mix"] = {
        "faulty_in_rare_regime": int((np.logical_not(seen) & (y == 1)).sum()),
        "fault_free_in_rare_regime": int((np.logical_not(seen) & (y == 0)).sum()),
        "temperature_counts_faulty": dict(Counter(temp[y == 1].tolist())),
        "temperature_counts_fault_free": dict(Counter(temp[y == 0].tolist())),
        "episodes_with_fault": len(fault_eps), "episodes": len(set(meta["episodes"])),
    }  # fmt: skip
    for name in MODELS:
        s = d[f"score_{name}"].astype(np.float64)
        res["placebo"][name] = placebo(s, later, stage, groups)
        res["seen_regime"][name] = subset_metrics(s, y, stage, seen, meta["episodes"])
        res["seen_recall"][name] = seen_recall(m.cross_fit_alarms(s, y, folds, 0.05), kind, seen)
        res["by_temperature"][name] = {
            str(t): subset_metrics(s, y, stage, temp == t) for t in sorted(set(temp.tolist()))
        }
    out.write_text(json.dumps(res, indent=1))
    return res

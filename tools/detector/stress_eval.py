"""Metrics of the stress settings at the fixed clean threshold, with episode bootstrap."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import evaluate as ev
import metrics as m
import numpy as np
from numpy.typing import NDArray

Floats = NDArray[np.float64]
BELOW_ALL = -1.0  # unscorable windows rank under every scorable one (scores are at least 0)


def clean_thresholds(clean: Floats, y: m.Ints, folds: m.Ints) -> Floats:
    """Per parity fold: 95th percentile of the clean fault-free scores of the other fold."""
    out = np.zeros(2)
    for f in (0, 1):
        out[f] = np.percentile(clean[(folds != f) & (y == 0)], 95)
    return out


def _ci(point: tuple[float, float, float]) -> list[float]:
    return [round(v, 4) for v in point]


def one_setting(s: Floats, c: ev.Context, thr: Floats) -> dict[str, Any]:
    """Discrimination and fixed-threshold alarm rates for one perturbed score."""
    live = ~np.isnan(s)
    filled = np.where(live, s, BELOW_ALL)
    alarms = live & (filled > thr[c.folds])

    def rate(i: m.Ints, sel: NDArray[np.bool_]) -> float:
        chosen = sel[i]
        return float(alarms[i][chosen].mean()) if chosen.any() else float("nan")

    free, bad = c.y == 0, c.y == 1
    return {
        "ap": _ci(m.interval(lambda i: m.average_precision(filled[i], c.y[i]), c.idx, c.res)),
        "matched_auroc": _ci(
            m.interval(lambda i: m.matched_stage_auroc(filled[i], c.y[i], c.stage[i]), c.idx, c.res)
        ),
        "far": _ci(m.interval(lambda i: rate(i, free), c.idx, c.res)),
        "recall": _ci(m.interval(lambda i: rate(i, bad), c.idx, c.res)),
        "scorable_all": round(float(live.mean()), 4),
        "scorable_faulty": round(float(live[bad].mean()), 4),
    }


def run(cv_dir: Path, stress_dir: Path, out: Path) -> dict[str, Any]:
    """All settings out of fold and on validation."""
    stored = np.load(stress_dir / "stress.npz")
    res: dict[str, Any] = {}
    for tag in ("oof", "val"):
        d = np.load(cv_dir / f"{tag}.npz")
        meta = json.loads((cv_dir / f"{tag}_meta.json").read_text())
        c = ev.Context(d, meta)
        clean = stored[f"{tag}_clean"]
        thr = clean_thresholds(clean, c.y, c.folds)
        names = [k[len(tag) + 1 :] for k in stored.files if k.startswith(tag + "_")]
        res[tag] = {n: one_setting(stored[f"{tag}_{n}"], c, thr) for n in names}
        res[tag]["clean_vs_saved_max_abs_diff"] = float(np.abs(clean - d["score_C3"]).max())
        res[tag]["thresholds"] = [round(float(t), 4) for t in thr]
    out.write_text(json.dumps(res, indent=1))
    return res

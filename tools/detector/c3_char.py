"""Characterisation of C3 alone: window level, alarm policies, controls and residual signatures.

Reads the saved scores of the baseline grouped-CV system (C3 is the same in every system) and
writes one results file. Thresholds are calibrated on fault-free episodes the scored windows'
model did not see.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv_eval
import numpy as np
import policies as p
import policy_eval as pe
import signature as sig
from numpy.typing import NDArray

Ints = NDArray[np.intp]


def _calibration(e: p.Episodes, mask: NDArray[np.bool_]) -> list[int]:
    """Indices of fault-free episodes selected by a per-episode mask."""
    return [i for i in range(len(e.order)) if mask[i] and not e.ep_faulty[i]]


def oof_state(e: p.Episodes, k: int, n: int) -> tuple[p.Bools, list[float]]:
    """Policy state out of fold: each fold's threshold comes from the other folds."""
    state = np.zeros(len(e.scores), dtype=bool)
    thresholds = []
    for f in np.unique(e.ep_fold):
        thr = p.calibrate(e, _calibration(e, e.ep_fold != f), k, n, p.EPISODE_TARGET)
        mine = [i for i in range(len(e.order)) if e.ep_fold[i] == f]
        state |= p.alarm_state(e, thr, k, n, mine)
        thresholds.append(thr)
    return state, thresholds


def val_state(e: p.Episodes, ref: p.Episodes, k: int, n: int) -> tuple[p.Bools, list[float]]:
    """Policy state on validation with the threshold from the out-of-fold train scores."""
    thr = p.calibrate(ref, _calibration(ref, np.ones(len(ref.order), dtype=bool)), k, n,
                      p.EPISODE_TARGET)  # fmt: skip
    return p.alarm_state(e, thr, k, n), [thr]


def policy_report(e: p.Episodes, state: p.Bools, thresholds: list[float]) -> dict[str, Any]:
    """All episode-level numbers and controls of one policy."""
    c = pe.Context(e)
    return {
        "thresholds": [round(t, 4) for t in thresholds],
        "false_alarms": pe.false_alarms(e, state, c),
        "detection": pe.detection(e, state, c),
        "delay": pe.delays(e, state),
        "window_recall": pe.window_recall(e, state, c),
        "shuffle_detection": pe.shuffle_detection(e, state),
        "placebo_rate_difference": pe.placebo_rate(e, state, c),
    }


def load(work: Path, tag: str) -> tuple[Any, dict[str, Any]]:
    """Arrays and metadata of one saved set."""
    return np.load(work / f"{tag}.npz"), json.loads((work / f"{tag}_meta.json").read_text())


def run(work: Path, out: Path) -> dict[str, Any]:
    """Compute everything for out of fold and validation and write the results."""
    d_o, m_o = load(work, "oof")
    d_v, m_v = load(work, "val")
    fold = d_o["fold"].astype(np.intp)
    e_o = p.build(d_o, m_o, d_o["score_C3"].astype(np.float64), fold)
    e_v = p.build(d_v, m_v, d_v["score_C3"].astype(np.float64))
    res: dict[str, Any] = {"oof": {"policies": {}}, "val": {"policies": {}}}
    for k, n in p.POLICIES:
        name = f"{k}/{n}"
        res["oof"]["policies"][name] = policy_report(e_o, *oof_state(e_o, k, n))
        res["val"]["policies"][name] = policy_report(e_v, *val_state(e_v, e_o, k, n))
    for tag in ("oof", "val"):
        res[tag]["window_level"] = cv_eval.evaluate_set(work, tag, ["C3"])
    parts_o, parts_v = d_o["parts_C3"].astype(np.float64), d_v["parts_C3"].astype(np.float64)
    y_o, y_v = d_o["faulty"].astype(np.intp), d_v["faulty"].astype(np.intp)
    thr_o = sig.fold_thresholds(parts_o, y_o, fold)
    thr_v = sig.reference_thresholds(parts_o, y_o, len(y_v))
    res["oof"]["signature"] = sig.matrix(parts_o, thr_o, np.asarray(m_o["kind"]), y_o)
    res["val"]["signature"] = sig.matrix(parts_v, thr_v, np.asarray(m_v["kind"]), y_v)
    res["classification"] = sig.agreement(res["oof"]["signature"], res["val"]["signature"])
    out.write_text(json.dumps(res, indent=1))
    return res

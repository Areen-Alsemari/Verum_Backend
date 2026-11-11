"""Fit the candidates on fault-free train windows and score the validation windows.

Labels are used here only to select the fault-free train windows. The scores are written to a
work folder together with the metadata needed to evaluate them, so that the evaluation step
never reads the data folder again.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path
from typing import Any, cast

import conditions
import cusum
import guard
import numpy as np
from candidates import GROUPS, PcaMonitor, PerTag, Residuals, Scored, fuse
from numpy.typing import NDArray
from windows import NUMERIC_TAGS, Windows, load_split, subset

SEED = 20261108
Floats = NDArray[np.float64]


def score_current_model(val: Windows) -> tuple[Floats, float]:
    """The current Agent 2 forest as is: raw positive-class score and its shipped threshold."""
    import verum.agents.anomaly_detection.agent as agent

    art = agent.load_artifact()
    out = []
    for signals in val.signals:
        feats = agent.extract_features(agent.filter_valid_unit_signals(signals))
        out.append(agent.decision_score(art["model"], feats, art["feature_names"]))
    return np.asarray(out, dtype=np.float64), float(art["threshold"])


def raw_pass(rel: Path, c1: PerTag, w: Windows) -> tuple[Floats, Floats]:
    """CUSUM maximum and raw window mean per tag, from the raw rows of the window."""
    mu, sigma = c1.cusum_params(w)
    return cusum.compute(rel, w.episodes, w.cutoff, mu, sigma)


def fit_and_score(
    rel: Path, train: Windows, val: Windows
) -> tuple[dict[str, Scored], dict[str, Floats], Floats]:
    """Fit C1 to C3 on train, score validation, fuse into C4. Returns raw validation means too."""
    c1 = PerTag(train)
    s_train, _ = raw_pass(rel, c1, train)
    s_val, raw_val = raw_pass(rel, c1, val)
    c1.calibrate(s_train)
    c3 = Residuals(train)
    out: dict[str, Scored] = {}
    for suffix in ("", "s"):
        guard_on = suffix == "s"
        c2a = PcaMonitor(train, c1.base, {"all": list(NUMERIC_TAGS)}, guard_on)
        c2b = PcaMonitor(train, c1.base, GROUPS, guard_on)
        tr = {
            "C1": c1.score(train, s_train, guard_on).scores,
            "C2a": c2a.score(train).scores,
            "C2b": c2b.score(train).scores,
            "C3": c3.score(train).scores,
        }
        got = {
            "C1": c1.score(val, s_val, guard_on),
            "C2a": c2a.score(val),
            "C2b": c2b.score(val),
            "C3": c3.score(val),
        }
        got["C4"] = fuse(tr, {k: got[k].scores for k in tr})
        for key, value in got.items():
            if suffix == "" or key != "C3":
                out[key + suffix] = value
    return out, {}, np.concatenate([s_val, raw_val], axis=1)


def run(rel: Path, work: Path, key: str = "lineup") -> dict[str, Any]:
    """Load, fit, score and save. Returns the metadata written next to the scores.

    The key is 'lineup' (the on/off tags, first experiment) or 'conditions' (Amendment 2).
    """
    assert key in ("lineup", "conditions")
    t0 = time.time()
    guard.install()
    val = load_split(rel, "validation", keep_signals=True)
    train_all = load_split(rel, "train")
    guard.ALLOWED_EPISODES.update(val.episodes)
    guard.ALLOWED_EPISODES.update(train_all.episodes)
    if key == "conditions":
        conds = conditions.read_conditions(rel, [*train_all.episodes, *val.episodes])
        train_all, val = conditions.apply(train_all, conds), conditions.apply(val, conds)
    train = subset(train_all, train_all.faulty == 0)
    out, _, extra = fit_and_score(rel, train, val)
    c0, threshold = score_current_model(val)
    meta = save(work, val, train, out, c0, threshold, extra, time.time() - t0)
    meta["regime_key"] = key
    (work / "meta.json").write_text(json.dumps(meta))
    return meta


def save(
    work: Path, val: Windows, train: Windows, out: dict[str, Scored], c0: Floats,
    threshold: float, extra: Floats, seconds: float,
) -> dict[str, Any]:  # fmt: skip
    """Write the score arrays and the metadata."""
    work.mkdir(parents=True, exist_ok=True)
    n = len(NUMERIC_TAGS)
    rng = np.random.default_rng(SEED)
    arrays: dict[str, Floats] = {
        "faulty": val.faulty.astype(np.float64), "stage": val.stage.astype(np.float64),
        "x": val.x, "cusum": extra[:, :n], "score_always_flag": np.zeros(len(val.ids)),
        "score_random": rng.random(len(val.ids)), "score_C0": c0,
    }  # fmt: skip
    for name, scored in out.items():
        arrays[f"score_{name}"] = scored.scores
        arrays[f"parts_{name}"] = scored.parts
    np.savez_compressed(work / "scores.npz", **cast(dict[str, Any], arrays))
    diff = np.abs(extra[:, n:] - val.x[:, :, 0])
    meta = {
        "ids": val.ids, "episodes": val.episodes, "kind": val.kind, "c0_threshold": threshold,
        "part_names": {k: v.names for k, v in out.items()}, "seconds": seconds,
        "train_windows": len(train.ids), "validation_windows": len(val.ids),
        "raw_mean_vs_summary_max_abs_diff": float(np.nanmax(diff)),
        "raw_mean_vs_summary_share_over_1e-6": float(np.nanmean(diff > 1e-6)),
        "missing_share_validation": float(np.isnan(val.x).mean()),
        "missing_share_train": float(np.isnan(train.x).mean()),
        "rare_regime_share_validation": rare_share(val, train), "guard": guard.summary(),
        "worker_guard": cusum.WORKER_GUARD,
    }  # fmt: skip
    (work / "meta.json").write_text(json.dumps(meta))
    return meta


def rare_share(val: Windows, train: Windows) -> float:
    """Share of validation windows in a regime with fewer than 200 fault-free train windows."""
    counts = Counter(train.regime)
    return float(np.mean([counts.get(r, 0) < 200 for r in val.regime]))

"""Grouped cross-validation over train by whole unit, and the validation benchmark.

Each fold is fitted on the fault-free windows of the other units only and scores every window
of the held-out units. The out-of-fold scores of all eligible train windows are saved together
with the metadata the evaluation needs, so that it never reads the data folder again.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, cast

import conditions
import guard
import numpy as np
from candidates import Residuals, pump_state
from fitting import Floats
from systems import Result, Spec, fold_map, score_system
from windows import NUMERIC_TAGS, Windows, load_split, subset

FOLDS = 5
SENSOR = ("bias", "drift", "stuck")


def regime_prior(all_fit: Windows, apply: Windows) -> Floats:
    """Condition-only reference: fault prevalence of the window's regime among the fit windows."""
    hits: dict[object, list[int]] = defaultdict(list)
    for r, y in zip(all_fit.regime, all_fit.faulty, strict=True):
        hits[r].append(int(y))
    overall = float(all_fit.faulty.mean())
    return np.asarray([np.mean(hits[r]) if r in hits else overall for r in apply.regime])


def _place(store: dict[str, Floats], key: str, rows: Floats, where: Any, n: int) -> None:
    shape = (n, *rows.shape[1:])
    store.setdefault(key, np.full(shape, np.nan))[where] = rows


def out_of_fold(train: Windows, spec: Spec) -> dict[str, Floats]:
    """OOF arrays for all train windows: scores, parts, tags and the condition-only prior."""
    folds = fold_map(train.unit, FOLDS)
    which = np.asarray([folds[u] for u in train.unit])
    store: dict[str, Floats] = {"fold": which.astype(np.float64)}
    for k in range(FOLDS):
        held = which == k
        fit_all = subset(train, ~held)
        fit = subset(fit_all, fit_all.faulty == 0)
        apply = subset(train, held)
        _place_result(store, score_system(fit, apply, spec), np.flatnonzero(held), len(which))
        _place(store, "score_prior", regime_prior(fit_all, apply), held, len(which))
    return store


def _place_result(store: dict[str, Floats], res: Result, where: Any, n: int) -> None:
    for name, s in res.scores.items():
        _place(store, f"score_{name}", s, where, n)
        _place(store, f"parts_{name}", res.parts[name], where, n)
    _place(store, "tags", res.tags, where, n)


def validation_run(train: Windows, val: Windows, spec: Spec) -> dict[str, Floats]:
    """Fit on all fault-free train windows and score validation."""
    store: dict[str, Floats] = {}
    res = score_system(subset(train, train.faulty == 0), val, spec)
    _place_result(store, res, np.arange(len(val.ids)), len(val.ids))
    _place(store, "score_prior", regime_prior(train, val), np.arange(len(val.ids)), len(val.ids))
    return store


def true_tags(w: Windows, conds: dict[str, conditions.Condition]) -> list[str]:
    """The faulty tag of single-component sensor-fault windows of one-fault episodes, else ''."""
    out = []
    for e, kind in zip(w.episodes, w.kind, strict=True):
        faults = conds[e].faults
        ok = kind in SENSOR and len(faults) == 1 and faults[0][1] in NUMERIC_TAGS
        out.append(faults[0][1] if ok else "")
    return out


def save(
    work: Path, tag: str, w: Windows, store: dict[str, Floats], conds: Any, names: Any
) -> None:
    """Write the arrays and the metadata of one evaluation set."""
    arrays = {k: v for k, v in store.items()} | {
        "faulty": w.faulty.astype(np.float64), "stage": w.stage.astype(np.float64),
        "x": w.x, "cutoff": w.cutoff, "onset_s": w.onset_s,
    }  # fmt: skip
    np.savez_compressed(work / f"{tag}.npz", **cast(dict[str, Any], arrays))
    meta = {
        "ids": w.ids, "episodes": w.episodes, "kind": w.kind, "part_names": names,
        "units": [list(u) for u in w.unit], "true_tag": true_tags(w, conds),
        "regimes": [list(r) for r in w.regime],
    }  # fmt: skip
    (work / f"{tag}_meta.json").write_text(json.dumps(meta))


def run(rel: Path, work: Path, spec: Spec) -> None:
    """Load train and validation, run grouped CV and the validation benchmark, save both."""
    guard.install()
    val = load_split(rel, "validation")
    train = load_split(rel, "train")
    guard.ALLOWED_EPISODES.update(val.episodes)
    guard.ALLOWED_EPISODES.update(train.episodes)
    conds = conditions.read_conditions(rel, [*train.episodes, *val.episodes])
    train, val = conditions.apply(train, conds), conditions.apply(val, conds)
    work.mkdir(parents=True, exist_ok=True)
    names = score_names(spec)
    save(work, "oof", train, out_of_fold(train, spec), conds, names)
    save(work, "val", val, validation_run(train, val, spec), conds, names)
    info = {
        "label": spec.label, "guard": guard.summary(), "mass_balance": mass_terms(train, spec),
        "pump_states": {n: pump_counts(w) for n, w in (("train", train), ("validation", val))},
    }  # fmt: skip
    (work / "spec.json").write_text(json.dumps(info))


def pump_counts(w: Windows) -> dict[str, int]:
    """Windows per pump state (A, B, AB, none), from the pump run tags."""
    counts = Counter(pump_state(r) for r in w.lineup)
    return {k: counts.get(k, 0) for k in ("A", "B", "AB", "none")}


def mass_terms(train: Windows, spec: Spec) -> dict[str, float]:
    """Fitted R1 terms on all fault-free train windows: tank areas, intercept, flow terms."""
    fit = subset(train, train.faulty == 0)
    coef = Residuals(fit, flow_terms=spec.e2).mass.coef
    names = ["area_LT-101", "area_LT-102", "area_LT-103", "intercept", "FT-201_mean", "setpoint"]
    return {n: round(float(v), 6) for n, v in zip(names, coef, strict=False)}


def score_names(spec: Spec) -> dict[str, list[str]]:
    """Part names of every score; they do not depend on the data."""
    tags = list(NUMERIC_TAGS)
    c3 = [*Residuals.NAMES, *(Residuals.PAIR_NAMES if spec.e3 else [])]
    return {"C1n": tags, "C2a": tags, "C2b": tags, "C3": c3, "C4": ["C1n", "C2a", "C2b", "C3"]}

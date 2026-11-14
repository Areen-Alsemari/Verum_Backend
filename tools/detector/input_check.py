"""Minimal-input check of the pooled C3: which fields it reads, tested by perturbation.

The scores must not change when every other statistic is overwritten, when the regime key and
the order of the windows are scrambled, or when a window is scored alone. The contract example
request is read, unchanged, to confirm that each field is a field of its summary signals.
"""

from __future__ import annotations

import json
from dataclasses import fields, replace
from pathlib import Path
from typing import Any

import cv
import numpy as np
import windows as win
from candidates import Residuals
from stress import NUMERIC_INPUTS
from windows import NUMERIC_TAGS, Windows, subset

STAT_FIELD = {0: "mean", 1: "slope_per_s"}
ALONE = 100


def field_list() -> list[tuple[str, str]]:
    """The twelve (tag, summary field) pairs the pooled C3 reads."""
    rows = [(tag, STAT_FIELD[stat]) for tag, stat in NUMERIC_INPUTS]
    return [*rows, ("P-101A", "latest_value"), ("P-101B", "latest_value")]


def permute(w: Windows, order: np.ndarray[Any, Any]) -> Windows:
    """The windows in a new order."""
    changed: dict[str, Any] = {}
    for f in fields(w):
        v = getattr(w, f.name)
        if isinstance(v, np.ndarray) and len(v) == len(order):
            changed[f.name] = v[order]
        elif isinstance(v, list) and len(v) == len(order):
            changed[f.name] = [v[i] for i in order]
    return replace(w, **changed)


def perturbation_check(model: Residuals, w: Windows) -> dict[str, float]:
    """Largest absolute score change under the three perturbations of the plan."""
    clean = model.score(w).scores
    x = np.full_like(w.x, 12345.0)
    for tag, stat in NUMERIC_INPUTS:
        j = NUMERIC_TAGS.index(tag)
        x[:, j, stat] = w.x[:, j, stat]
    other = model.score(replace(w, x=x)).scores
    order = np.random.default_rng(1).permutation(len(w.ids))
    garbage = replace(w, regime=[("x", float(i), -1.0) for i in range(len(w.ids))])
    scrambled = model.score(permute(garbage, order)).scores
    alone = np.asarray(
        [model.score(subset(w, np.arange(len(w.ids)) == i)).scores[0] for i in range(ALONE)]
    )
    return {
        "other_statistics_overwritten": float(np.abs(other - clean).max()),
        "regime_and_order_scrambled": float(np.abs(scrambled[np.argsort(order)] - clean).max()),
        "window_scored_alone": float(np.abs(alone - clean[:ALONE]).max()),
    }


def request_check(path: Path, model: Residuals) -> dict[str, Any]:
    """Confirm the twelve fields in a contract example request and score its window."""
    from verum.agents.anomaly_detection.agent import EXPECTED_UNITS

    req = json.loads(path.read_text())
    by_tag = {s["tag_id"]: s for s in req["input"]["observations"]["summary"]["signals"]}
    rows = []
    for tag, name in field_list():
        sig = by_tag.get(tag, {})
        value = sig.get(name)
        ok = isinstance(value, (int, float))
        rows.append({"tag": tag, "field": name, "unit": sig.get("unit"),
                     "unit_expected": EXPECTED_UNITS.get(tag), "value_present": ok})  # fmt: skip
    one = _single_window(by_tag)
    got = model.score(one)
    return {
        "representation": req["input"]["observations"]["representation"],
        "fields": rows, "all_present": all(r["value_present"] for r in rows),
        "units_match": all(r["unit"] == r["unit_expected"] for r in rows),
        "example_score": round(float(got.scores[0]), 4),
        "example_residuals": [round(float(v), 4) for v in got.parts[0]],
    }  # fmt: skip


def _single_window(by_tag: dict[str, dict[str, Any]]) -> Windows:
    x = np.asarray([[[win._value(by_tag[t], s) for s in win.STATS] for t in NUMERIC_TAGS]])
    key = win._regime(by_tag)
    return Windows(["request"], ["request"], np.ones(1, dtype=np.intp), np.zeros(1),
                   np.zeros(1, dtype=np.intp), ["none"], x, [key], [()])  # fmt: skip


def run(rel: Path, request: Path, out: Path) -> dict[str, Any]:
    """Fit the pooled model on all fault-free train windows and run both checks."""
    train, val, _ = cv.load_conditioned(rel)
    model = Residuals(subset(train, train.faulty == 0), pooled_r4=True)
    res = {"perturbation": perturbation_check(model, val), "request": request_check(request, model)}
    out.write_text(json.dumps(res, indent=1))
    return res

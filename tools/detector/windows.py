"""Load train and validation windows as arrays: allowed statistics, regime key and labels.

Only the allowed columns are built: mean, slope and the square root of the standard deviation
of the 14 numeric tags. The on/off tags give the regime key and nothing else. Labels are kept
in separate arrays and are used for selecting fit windows and for scoring, never as inputs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import guard
import numpy as np
from numpy.typing import NDArray

NUMERIC_TAGS = (
    "FT-001", "FT-201", "LT-101", "LT-102", "LT-103", "PT-001", "PT-201", "PT-202A",
    "PT-202B", "PT-203", "TT-001", "TT-101", "TT-102", "TT-103",
)  # fmt: skip
BOOL_TAGS = (
    "LSHH-101", "LSHH-102", "LSHH-103", "P-101A", "P-101B", "XV-PAI", "XV-PAO", "XV-PBI",
    "XV-PBO", "XV-R000", "XV-R101", "XV-R102", "XV-R103", "XV-S101", "XV-S102", "XV-S103",
)  # fmt: skip
STATS = ("mean", "slope_per_s", "spread")
SOURCE_FIELD = {"mean": "mean", "slope_per_s": "slope_per_s", "spread": "standard_deviation"}
MECHANISM_GROUP = {
    "restriction_position_visible": "restriction", "restriction_obstruction": "restriction",
    "pump": "pump", "bias": "bias", "drift": "drift", "stuck": "stuck", "leak": "leak",
    "misroute_a": "misrouting", "misroute_b": "misrouting",
}  # fmt: skip
FAULT_TYPES = ("restriction", "pump", "bias", "drift", "stuck", "leak", "misrouting", "multi")


def feature_columns() -> list[str]:
    """The complete list of allowed summary columns, tag by tag."""
    return [f"{tag}:{stat}" for tag in NUMERIC_TAGS for stat in STATS]


@dataclass
class Windows:
    """Eligible windows of one split."""

    ids: list[str]
    episodes: list[str]
    stage: NDArray[np.intp]
    cutoff: NDArray[np.float64]
    faulty: NDArray[np.intp]
    kind: list[str]
    x: NDArray[np.float64]
    regime: list[tuple[int, ...]]
    signals: list[Any] = field(default_factory=list)


def fault_kind(components: list[dict[str, Any]]) -> str:
    """Fault type of a window: none, one of the single types, or multi."""
    if not components:
        return "none"
    if len(components) > 1:
        return "multi"
    return MECHANISM_GROUP[components[0]["mechanism"]]


def _value(signal: dict[str, Any], stat: str) -> float:
    raw = signal.get(SOURCE_FIELD[stat])
    if not isinstance(raw, (int, float)) or isinstance(raw, bool) or not math.isfinite(raw):
        return float("nan")
    return math.sqrt(max(raw, 0.0)) if stat == "spread" else float(raw)


def _regime(by_tag: dict[str, dict[str, Any]]) -> tuple[int, ...]:
    key = []
    for tag in BOOL_TAGS:
        raw = by_tag.get(tag, {}).get("latest_value")
        key.append(int(round(raw)) if isinstance(raw, (int, float)) else -1)
    return tuple(key)


def load_split(rel: Path, split: str, keep_signals: bool = False) -> Windows:
    """All windows with a valid label of 'train' or 'validation'."""
    assert split in guard.KEPT_SPLITS, "only train and validation may be loaded"
    from verum.agents.common import episode_lookup, iter_role_records

    lineage = episode_lookup(rel, split)
    cols: dict[str, list[Any]] = {k: [] for k in ("ids", "ep", "stage", "cut", "y", "kind", "x")}
    regimes: list[tuple[int, ...]] = []
    kept: list[Any] = []
    for rec in iter_role_records(rel, "diagnostic_reasoning", split):
        if not rec.target["supervised_loss_mask"]:
            continue
        ref = lineage[rec.example_id]
        by_tag = {s["tag_id"]: s for s in rec.input["observations"]["signals"]}
        comps = rec.target["injected_components"] or []
        cols["ids"].append(rec.example_id)
        cols["ep"].append(ref.episode_id)
        cols["stage"].append(int(round(ref.source_cutoff_s / 300.0)))
        cols["cut"].append(float(ref.source_cutoff_s))
        cols["y"].append(1 if comps else 0)
        cols["kind"].append(fault_kind(comps))
        cols["x"].append([[_value(by_tag[t], s) for s in STATS] for t in NUMERIC_TAGS])
        regimes.append(_regime(by_tag))
        if keep_signals:
            kept.append(rec.input["observations"]["signals"])
    return Windows(
        cols["ids"], cols["ep"], np.asarray(cols["stage"], dtype=np.intp),
        np.asarray(cols["cut"]), np.asarray(cols["y"], dtype=np.intp), cols["kind"],
        np.asarray(cols["x"], dtype=np.float64), regimes, kept,
    )  # fmt: skip


def subset(w: Windows, mask: NDArray[np.bool_]) -> Windows:
    """The windows selected by a boolean mask."""
    idx = np.flatnonzero(mask)
    pick = [int(i) for i in idx]
    return Windows(
        [w.ids[i] for i in pick], [w.episodes[i] for i in pick], w.stage[idx], w.cutoff[idx],
        w.faulty[idx], [w.kind[i] for i in pick], w.x[idx], [w.regime[i] for i in pick],
        [w.signals[i] for i in pick] if w.signals else [],
    )  # fmt: skip

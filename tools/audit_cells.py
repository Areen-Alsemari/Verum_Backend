"""Margins, classes and time to detect of the cells of the fault grid.

A cell is one fault of one type on one asset at one severity. Its features are compared with the
calibrated thresholds of its profile and lineup, multiplied by the scale factor. The margin is the
largest deviation over all windows divided by the scaled threshold, best over the window lengths
and worst over the five design draws. The held margin and the time to detect use three consecutive
windows. A contact or run status that changes after the onset is a margin of 3 at once.

See D79 to D81 and D89.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from audit_collect import path_of
from audit_features import (
    DRAWS,
    LAYOUT,
    WINDOWS_S,
    contact_changes,
    features,
    load_run,
    window_ends,
)

from verum.evaluation.agent_audit import exceedance, held
from verum.faults import FaultSpec, LineupState, activity

ONSET_S = 900.0
HELD_WINDOWS = 3
CLEAR = 3.0
Thresholds = dict[str, dict[str, Any]]


@dataclass
class Cell:
    kind: str
    fault: str
    family: str
    asset: str
    index: int
    profile: str
    label: str


def parse(label: str) -> Cell | None:
    """Split a label of a fault run or a sensor case; healthy labels give None."""
    p = label.split("|")
    if p[0] in ("cal", "held"):
        return None
    if p[0] == "case":
        return Cell(p[1], p[1], p[2], p[3], int(p[4]), p[5], label)
    mode = p[4]
    fault = f"restriction_{mode}" if p[0] == "restriction" else p[0]
    return Cell(p[0], fault, p[1], p[2], int(p[3]), p[5], label)


SPECS = {
    "leak": ("PIPE_LEAK", "orifice"),
    "restriction": ("VALVE_RESTRICTION", "restriction"),
    "pump": ("PUMP_HEAD_DEGRADATION", "head_scale"),
    "bias": ("SENSOR_DRIFT", "bias"),
    "drift": ("SENSOR_DRIFT", "drift"),
    "stuck": ("SENSOR_DRIFT", "stuck"),
    "misroute_a": ("VALVE_MISROUTING", "closed_but_open"),
    "misroute_b": ("VALVE_MISROUTING", "open_but_stuck"),
}


def activity_of(cell: Cell, modes: Any) -> str:
    """Latent or active, from the lineup of the family (receipt set-point 600 when receiving)."""
    mode, _deliver, receive = LAYOUT[cell.family]
    m = modes.mode(mode)
    state = LineupState(
        frozenset(m.open_valves), frozenset(m.running_pumps), 600.0 if receive else 0.0
    )
    ftype, variant = SPECS[cell.kind]
    restriction = cell.fault.split("_", 1)[1] if cell.kind == "restriction" else None
    return activity(
        FaultSpec(ftype, variant, cell.asset, ONSET_S, 300.0, 0.5, fault_mode=restriction), [state]
    )


def per_draw(
    feats: dict[tuple[int, str], np.ndarray], th: Thresholds, scale: float
) -> dict[int, dict[str, Any]]:
    """Largest and held scaled margin per window length, with the exceedance of every feature."""
    out: dict[int, dict[str, Any]] = {}
    for length in WINDOWS_S:
        z = {
            n: exceedance(s, th[f"{k}|{n}"]["mean"], th[f"{k}|{n}"]["value"] * scale)
            for (k, n), s in feats.items()
            if k == length and f"{k}|{n}" in th
        }
        best = max(z, key=lambda n: float(z[n].max()))
        out[length] = {
            "margin": float(z[best].max()),
            "dominant": best,
            "held": max(float(held(v).max()) for v in z.values()),
            "z": z,
        }
    return out


def detect_time(z: dict[str, np.ndarray]) -> float | None:
    """Seconds after the onset at the end of the first three consecutive windows above 1."""
    ends = window_ends()
    firsts = []
    for v in z.values():
        ok = np.nonzero((held(v) > 1.0) & (ends > ONSET_S))[0]
        if len(ok):
            firsts.append(float(ends[ok[0]]) - ONSET_S)
    return min(firsts) if firsts else None


def evaluate(
    label: str, th: Thresholds, scale: float = 1.0, onset_s: float = ONSET_S
) -> dict[str, Any]:
    """Scaled margins of one stored run (a fault cell or a healthy run).

    The margin is the largest over window lengths for the worst of the design draws, the same
    quantity that fixes the scale factor on healthy runs. ``unscaled_margin`` is the margin of the
    thresholds before the factor.
    """
    cell = parse(label)
    fam = label.split("|")[1] if cell is None else cell.family
    run = load_run(path_of(label))
    if run.rejected:
        return {"label": label, "rejected": run.rejected}
    draws = [per_draw(features(run, fam, d), th, scale) for d in range(1, len(DRAWS))]
    by_draw = [max(d[length]["margin"] for length in WINDOWS_S) for d in draws]
    worst = int(np.argmin(by_draw))
    by_length = {str(w): min(d[w]["margin"] for d in draws) for w in WINDOWS_S}
    held_by_length = {str(w): min(d[w]["held"] for d in draws) for w in WINDOWS_S}
    detect = {
        str(w): detect_time(draws[int(np.argmin([d[w]["margin"] for d in draws]))][w]["z"])
        if by_length[str(w)] >= 1.0
        else None
        for w in WINDOWS_S
    }
    best = max(WINDOWS_S, key=lambda w: draws[worst][w]["margin"])
    changes = contact_changes(run.events, onset_s)
    margin, held_margin, discrete = by_draw[worst], max(held_by_length.values()), bool(changes)
    out: dict[str, Any] = {"label": label, "rejected": None, "scale": scale}
    out.update(
        unscaled_margin=margin * scale,
        margin=margin,
        by_length=by_length,
        held=held_margin,
        held_by_length=held_by_length,
        detect=detect,
        discrete=discrete,
        dominant="contact" if discrete else draws[worst][best]["dominant"],
        changed_tags=sorted({tag for _, tag in changes}),
        signature=signature(features(run, fam, 0), th),
    )
    if discrete:
        out["margin"] = max(margin, CLEAR)
        out["held"] = max(held_margin, CLEAR)
        out["by_length"] = {k: max(v, CLEAR) for k, v in by_length.items()}
        out["detect"] = {
            k: min([x for x in (v, changes[0][0] - onset_s) if x is not None])
            for k, v in detect.items()
        }
    return out


def signature(
    feats: dict[tuple[int, str], np.ndarray], th: Thresholds, length: int = 300
) -> dict[str, float]:
    """Signed deviation over threshold of each feature in the last window of the nominal design."""
    out = {}
    for (k, n), s in feats.items():
        if k == length and f"{k}|{n}" in th:
            t = th[f"{k}|{n}"]
            v = s[-1]
            out[n] = float((v - t["mean"]) / t["value"]) if np.isfinite(v) else 0.0
    return out

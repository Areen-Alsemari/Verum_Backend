"""Outcome models of the seven inspection actions.

Each model reads the true state at the performed time and returns the measured quantity: the true
quantity plus a Gaussian error with standard deviation U/2, where U is the expanded uncertainty of
the catalog. Every model draws the same four random numbers in the same order whatever the
outcome, so a result does not depend on a branch. The models of the rim seal and the fittings
return an intact result until the vapour track exists, and say so.

See D102, D103, D105 and D109.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from verum.inspection.assets import Assets
from verum.inspection.catalog import Catalog
from verum.inspection.truth import State
from verum.sensors import load_sensor_config

BAR_PA = 1.0e5
M3H = 3600.0
NORMAL, MINOR = "NORMAL_INTACT", "MINOR_DEGRADATION"
CRITICAL, INCONCLUSIVE = "CRITICAL_DEFECT", "TEST_INCONCLUSIVE"
VAPOUR_NOTE = (
    "The state of the rim seal and the fittings is not available in this release, "
    "so the result is reported intact."
)


@dataclass
class Outcome:
    name: str
    value: float
    unit: str
    uncertainty_k2: float
    category: str
    notes: list[str]
    evidence: str = "valid"
    true: dict[str, Any] = field(default_factory=dict)  # evaluator side, never serialised


def _draws(rng: np.random.Generator) -> tuple[float, float, float, float]:
    """Two normal numbers, one uniform and one more normal, always in this order."""
    z1, z2 = rng.standard_normal(2)
    u = rng.random()
    z3 = rng.standard_normal()
    return float(z1), float(z2), float(u), float(z3)


def _three_way(x: float, normal_max: float, critical_min: float) -> str:
    if x <= normal_max:
        return NORMAL
    return CRITICAL if x >= critical_min else MINOR


def rim_survey(c: Catalog, a: Assets, s: State, target: str, rng: np.random.Generator) -> Outcome:
    z1, *_ = _draws(rng)
    act = c.action("ACT-INSP-01")
    u = act.u("maximum_rim_seal_gap")
    value = max(0.0, z1 * u / 2.0)
    return Outcome("maximum_rim_seal_gap", value, "mm", u, NORMAL, [VAPOUR_NOTE], "low_confidence",
                   {"true_value": 0.0})  # fmt: skip


def valve_check(c: Catalog, a: Assets, s: State, target: str, rng: np.random.Generator) -> Outcome:
    z1, z2, *_ = _draws(rng)
    act = c.action("ACT-INSP-02")
    inbound, outbound = a.valve_edges(target)
    drop_bar = (
        s["edges"][inbound.edge_id]["p_to_pa_gauge"]
        - s["edges"][outbound.edge_id]["p_from_pa_gauge"]
    ) / BAR_PA
    u_dp, u_travel = act.u("measured_differential_pressure"), act.u("stem_travel")
    measured = drop_bar + z1 * u_dp / 2.0
    valve = s["valves"][target]
    travel = min(100.0, max(0.0, valve["position_frac"] * 100.0 + z2 * u_travel / 2.0))
    category = _three_way(
        measured, c.param("thresholds", "valve_dp_normal_max_bar"),
        c.param("thresholds", "valve_dp_critical_min_bar"),
    )  # fmt: skip
    notes = [
        f"Commanded state: {'open' if valve['commanded_open'] else 'closed'}.",
        f"Measured stem travel: {travel:.1f} percent (expanded uncertainty {u_travel:g} percent).",
        f"Open contact reads {'open' if valve['contact_open'] else 'closed'}.",
    ]
    true = {"true_value": drop_bar, "actual_opening_percent": valve["position_frac"] * 100.0}
    return Outcome("measured_differential_pressure", measured, "bar", u_dp, category, notes,
                   "valid", true)  # fmt: skip


def pump_vibration(
    c: Catalog, a: Assets, s: State, target: str, rng: np.random.Generator
) -> Outcome:
    z1, *_ = _draws(rng)
    act = c.action("ACT-INSP-03")
    v0 = c.param("models", "vibration_baseline_mm_s")
    v1 = c.param("models", "vibration_anchor_mm_s")
    h1 = c.param("models", "vibration_anchor_head_loss")
    loss = 1.0 - s["pumps"][target]["head_scale"]
    true = v0 + (v1 - v0) * loss / h1
    u = act.u("overall_velocity_rms")
    measured = true + z1 * u / 2.0
    category = _three_way(
        measured, c.param("thresholds", "vibration_normal_max_mm_s"),
        c.param("thresholds", "vibration_critical_min_mm_s"),
    )  # fmt: skip
    notes = ["The spectral peak ratios are not modelled."]
    return Outcome("overall_velocity_rms", measured, "mm/s", u, category, notes, "valid",
                   {"true_value": true, "head_loss_fraction": loss})  # fmt: skip


def detection_probability(q_m3h: float, q50_m3h: float) -> float:
    """P = 1 / (1 + (q50 / q)^2), and 0 without a leak."""
    return 0.0 if q_m3h <= 0.0 else 1.0 / (1.0 + (q50_m3h / q_m3h) ** 2)


def leak_survey(c: Catalog, a: Assets, s: State, target: str, rng: np.random.Generator) -> Outcome:
    _z1, _z2, u, z3 = _draws(rng)
    q50 = c.param("models", "acoustic_q50_m3h")
    sigma = c.param("models", "localisation_sigma_m")
    leaks = [x for x in s["leaks"] if x["edge_id"] == target]
    q = sum(x["flow_m3s"] for x in leaks) * M3H
    p = detection_probability(q, q50)
    detected = u < p
    notes = ["The acoustic level and the wall thickness are not modelled."]
    true: dict[str, Any] = {"true_value": q, "detection_probability": p}
    if detected:
        length = a.edges[target].length_m
        station = min(length, max(0.0, leaks[0]["fraction"] * length + z3 * sigma))
        notes.insert(
            0,
            f"Leak localised at {station:.1f} m from the upstream end of the edge "
            f"(standard deviation of the localisation error {sigma:g} m).",
        )
        true["true_station_m"] = leaks[0]["fraction"] * length
        return Outcome("leak_detected", 1.0, "1", 0.0, CRITICAL, notes, "valid", true)
    notes.insert(0, "No leak was detected; a small leak can stay below the detection limit.")
    return Outcome("leak_detected", 0.0, "1", 0.0, INCONCLUSIVE, notes, "low_confidence", true)


def dip_sounding(c: Catalog, a: Assets, s: State, target: str, rng: np.random.Generator) -> Outcome:
    z1, *_ = _draws(rng)
    act = c.action("ACT-INSP-05")
    u = act.u("manual_innage_level")
    true_mm = s["tanks"][target]["level_m"] * 1000.0
    measured = true_mm + z1 * u / 2.0
    tag = s["tags"][f"LT-{target[-3:]}"]
    reported_mm = (tag["value"] + tag["fault_offset"]) * 1000.0
    u_lt = c.param("models", "level_transmitter_uncertainty_mm")
    agree = abs(measured - reported_mm) <= math.hypot(u, u_lt)
    notes = ["The water bottom cut is not modelled."]
    category, evidence = (NORMAL, "valid") if agree else (INCONCLUSIVE, "low_confidence")
    if not agree:
        notes.insert(0, "The sounding differs from the level of the radar gauge beyond the "
                        "combined expanded uncertainty.")  # fmt: skip
    return Outcome("manual_innage_level", measured, "mm", u, category, notes, evidence,
                   {"true_value": true_mm, "reported_mm": reported_mm})  # fmt: skip


def fitting_check(
    c: Catalog, a: Assets, s: State, target: str, rng: np.random.Generator
) -> Outcome:
    _draws(rng)
    notes = [VAPOUR_NOTE, "The cracking pressure is not modelled."]
    return Outcome("seating_integrity", 0.0, "1", 0.0, NORMAL, notes, "low_confidence",
                   {"true_value": 0.0})  # fmt: skip


def loop_calibration(
    c: Catalog, a: Assets, s: State, target: str, rng: np.random.Generator
) -> Outcome:
    z1, *_ = _draws(rng)
    act = c.action("ACT-INSP-07")
    u = act.u("calibration_error")
    spec = load_sensor_config().tags[target]
    span_bar = spec.range_hi - spec.range_lo  # type: ignore[operator]
    offset_pa = s["tags"][target]["fault_offset"]
    true_pct = 100.0 * (-offset_pa / BAR_PA) / span_bar  # true pressure less the reported value
    measured = true_pct + z1 * u / 2.0
    u_pt = c.param("models", "pressure_transmitter_uncertainty_percent_span")
    agree = abs(measured) <= math.hypot(u, u_pt)
    category, evidence = (NORMAL, "valid") if agree else (INCONCLUSIVE, "low_confidence")
    notes = ["Five-point calibration summarised as the mean error."]
    if not agree:
        notes.insert(0, "The calibration error exceeds the combined expanded uncertainty.")
    return Outcome("calibration_error", measured, "percent of span", u, category, notes, evidence,
                   {"true_value": true_pct})  # fmt: skip


MODELS = {
    "ACT-INSP-01": rim_survey, "ACT-INSP-02": valve_check, "ACT-INSP-03": pump_vibration,
    "ACT-INSP-04": leak_survey, "ACT-INSP-05": dip_sounding, "ACT-INSP-06": fitting_check,
    "ACT-INSP-07": loop_calibration,
}  # fmt: skip


def perform(
    c: Catalog, a: Assets, s: State, action_id: str, target: str, rng: np.random.Generator
) -> Outcome:
    """The outcome of an action on a target in the true state ``s``."""
    return MODELS[action_id](c, a, s, target, rng)

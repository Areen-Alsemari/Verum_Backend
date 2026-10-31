"""The receipt switch of a campaign episode: its set-point schedule and its window check.

The set-point goes to zero in two stages, to the lowest permitted non-zero value at the start of the
closing stroke and to zero a few seconds later. The fall of the flow then outlasts the wave
criterion of the receipt path, and the flow at the end of the stroke stays below the flow that
makes a stroke window. The longest path keeps a window at the lowest set-point, which is not drawn.

See D22, D53, D58 and D153.
"""

from __future__ import annotations

import math
from typing import Any

from verum.campaign.eligibility import model_and_table
from verum.sim.config import load_sim_config
from verum.sim.path import receipt_edges
from verum.sim.validity import round_trip_s, wave_speeds

SWITCH_AT_S = 600.0
RESUME_AT_S = 1200.0
HOLD_S = 4.0
STAGE_ONE_M3H = 300.0
LOWEST_STEPPED_M3H = 400.0  # a set-point above the stage-one value is ramped in two stages
LIMITED_TANK = "TK-103"
CLOSING_FLOW_TIME_S = 8.0  # the instant at which the opening of the closing stroke falls to 0.2


def two_stage(setpoint_m3h: float) -> bool:
    return setpoint_m3h > STAGE_ONE_M3H


def setpoints_for(first_tank: str, allowed: tuple[float, ...]) -> tuple[float, ...]:
    """Set-points that give no window for a switch from the first tank (the longest receipt path
    keeps a window for a single step)."""
    if first_tank == LIMITED_TANK:
        return tuple(s for s in allowed if two_stage(s))
    return allowed


def schedule(first: str, second: str, setpoint_m3h: float) -> list[dict[str, Any]]:
    """Set-point and lineup commands of a switch from receipt ``first`` to receipt ``second``."""
    steps: list[dict[str, Any]] = [
        {"t_s": 0.0, "command": "receipt_setpoint", "value_m3h": setpoint_m3h}
    ]
    if two_stage(setpoint_m3h):
        steps.append(
            {"t_s": SWITCH_AT_S, "command": "receipt_setpoint", "value_m3h": STAGE_ONE_M3H}
        )
    steps.append(
        {"t_s": SWITCH_AT_S + (HOLD_S if two_stage(setpoint_m3h) else 0.0),
         "command": "receipt_setpoint", "value_m3h": 0.0}
    )  # fmt: skip
    steps += [
        {"t_s": SWITCH_AT_S, "command": "lineup", "mode": "SWITCH_RECEIPT_HOLD"},
        {"t_s": RESUME_AT_S, "command": "lineup", "mode": second},
        {"t_s": RESUME_AT_S, "command": "receipt_setpoint", "value_m3h": setpoint_m3h},
    ]
    return steps


def fall_time_s(setpoint_m3h: float, tau_s: float, high: float = 0.9, low: float = 0.1) -> float:
    """Time for the flow to fall from ``high`` to ``low`` of the set-point at the start of the
    stroke, for a first-order controller with the time constant ``tau_s``."""
    if not two_stage(setpoint_m3h):
        return tau_s * math.log(high / low)
    drop = setpoint_m3h - STAGE_ONE_M3H
    t_high = -tau_s * math.log((high * setpoint_m3h - STAGE_ONE_M3H) / drop)
    return _time_to_low(setpoint_m3h, tau_s, low, HOLD_S) - t_high


def _time_to_low(setpoint_m3h: float, tau_s: float, low: float, hold_s: float) -> float:
    at_hold = STAGE_ONE_M3H + (setpoint_m3h - STAGE_ONE_M3H) * math.exp(-hold_s / tau_s)
    return hold_s + tau_s * math.log(at_hold / (low * setpoint_m3h))


def closing_flow_m3h(setpoint_m3h: float, tau_s: float) -> float:
    """Flow at the instant the closing stroke reaches an opening of 0.2."""
    if not two_stage(setpoint_m3h):
        return setpoint_m3h * math.exp(-CLOSING_FLOW_TIME_S / tau_s)
    at_hold = STAGE_ONE_M3H + (setpoint_m3h - STAGE_ONE_M3H) * math.exp(-HOLD_S / tau_s)
    return at_hold * math.exp(-(CLOSING_FLOW_TIME_S - HOLD_S) / tau_s)


def table(setpoints: tuple[float, ...]) -> list[dict[str, Any]]:
    """Round trip, criterion, fall time and stroke flow for each receiving tank and set-point."""
    model, _ = model_and_table()
    cfg = load_sim_config()
    tau, factor = cfg["receipt_controller_tau_s"], cfg["wave_criterion_factor"]
    limit = cfg["stroke_window_min_flow_fraction"] * model.config["receipt_flow_m3h"]
    rows = []
    for tank in model.topology.tank_ids:
        trip = round_trip_s(model, receipt_edges(model, tank), wave_speeds(cfg))
        for sp in setpoints:
            fall = fall_time_s(sp, tau)
            flow = closing_flow_m3h(sp, tau)
            rows.append({
                "tank": tank, "setpoint_m3h": sp, "round_trip_s": trip,
                "criterion_s": factor * trip, "fall_s": fall,
                "collapse_window": fall < factor * trip,
                "closing_flow_m3h": flow, "stroke_window": flow >= limit,
            })  # fmt: skip
    return rows

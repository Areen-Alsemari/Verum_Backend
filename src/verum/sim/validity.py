"""Validity of the rigid-column model: the wave-round-trip criterion and the windows.

Inputs: the edges of a path, the screening wave speeds, an event duration and the
factor. Outputs: the wave round-trip time of a path, the ratio ``duration / round trip``
and the validity-window record.
Key assumptions:
    * Decisions D22 and D53: the rigid-column model is valid for an event only if the event
      lasts at least ``factor`` pressure-wave round trips of the path, ``duration >= factor * 2 *
      sum(L_i / a_i)``; the factor is 25 for a valve stroke and 10 for a receipt set-point step,
      a flow collapse and a path closure. The wave speeds are the screening
      values of the audited package for each nominal size; the factors are proposals.
    * Decision D54: an isolated segment (decision D39) whose held pressure is more than 0.5 bar
      from its target opens a ``dead_leg_unvalidated`` window, closed below 0.05 bar.
    * A window is the interval in which the model does not represent the physics, with
      the reason: a valve stroke or a set-point change shorter than the criterion, a flow
      that collapses within it, a flow stopped by a closing path, or a branched lineup for
      which no single rigid column exists. A window is hidden truth (decision D25).

Source: ``docs/design_decisions.md`` D22, D25, D53 and D54;
``revised/05_simulation_validation_dataset.md`` PAR-PIP-007 and VV-A2 (screening wave speeds).
"""

from __future__ import annotations

from dataclasses import dataclass

from verum.hydraulics import HydraulicModel
from verum.sim.config import SimConfig
from verum.sim.path import _dn

REASON_DURATION = "duration_below_wave_criterion"
REASON_COLLAPSE = "flow_collapse_within_wave_criterion"
REASON_STOPPED = "path_closed_with_flow"
REASON_BRANCHED = "rigid_column_unavailable"
REASON_DEAD_LEG = "dead_leg_held_pressure_unvalidated"
STROKE_FACTOR = "wave_criterion_factor_valve_stroke"
KINDS = (
    "valve_stroke", "receipt_setpoint", "flow_collapse", "path_closed", "branched_lineup",
    "dead_leg_unvalidated",
)  # fmt: skip


@dataclass
class ValidityWindow:
    window_id: str
    kind: str
    element_id: str
    t_start_s: float
    t_end_s: float | None
    reason: str
    ratio: float | None
    round_trip_s: float | None

    def as_row(self) -> dict[str, object]:
        return {
            "window_id": self.window_id,
            "kind": self.kind,
            "element_id": self.element_id,
            "t_start_s": self.t_start_s,
            "t_end_s": self.t_end_s,
            "reason": self.reason,
            "ratio": self.ratio,
            "round_trip_s": self.round_trip_s,
        }


def wave_speeds(cfg: SimConfig) -> dict[int, float]:
    return {200: cfg["wave_speed_dn200_m_s"], 250: cfg["wave_speed_dn250_m_s"],
            300: cfg["wave_speed_dn300_m_s"]}  # fmt: skip


def round_trip_s(
    model: HydraulicModel, edge_ids: tuple[str, ...], speeds: dict[int, float]
) -> float:
    """Time for a pressure wave to travel the path and return: ``2 sum L_i / a_i``."""
    total = 0.0
    for eid in edge_ids:
        e = model.topology.edge(eid)
        total += e.length_m / speeds[_dn(e.inner_diameter_m)]
    return 2.0 * total


def ratio(duration_s: float, round_trip: float) -> float:
    return duration_s / round_trip


def is_valid(duration_s: float, round_trip: float, factor: float) -> bool:
    return duration_s >= factor * round_trip

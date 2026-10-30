"""Fault specification records: the five single-fault types, severity and physical parameters.

Inputs: a mapping that describes one fault. Outputs: an immutable ``FaultSpec``, its severity
trajectory and the value of its physical parameter at any severity.
Key assumptions:
    * A specification is closed: the fields are fixed by ``schemas/fault_spec.schema.json`` and no
      field is left to a default that hides a physical choice. The magnitude is the physical value
      of the fault at severity one: the leak area (m2), the opening ceiling of a restricted or
      stuck valve, the head scale of a pump, the signed bias (fraction of span), the signed drift
      (fraction of span per hour), 0 for a stuck-at, 1 for a valve forced open.
    * The severity trajectory is piecewise linear in seconds since onset and holds its last value
      (the form of the audited ``fault_truth`` schema): knots ``(0, 0)`` and ``(ramp, peak)``, or
      the single knot ``(0, peak)`` for a step. ``peak`` is 1 except in the zero-fault test that
      checks a fault of severity 0 against the healthy episode.
    * Every physical parameter is a linear function of the severity.
    * A valve restriction names its mode (decision D74): ``position_visible`` (the actual opening
      is the ceiling and the open contact follows it) or ``obstruction`` (the loss follows the
      ceiling and the open contact still reads the stem position); no default is chosen for it.

Source: ``docs/design_decisions.md`` D60 to D65, D74; ``docs/fault_models.md``;
``schemas/fault_truth.schema.json``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from verum.contracts import validate

LEAK = "PIPE_LEAK"
RESTRICTION = "VALVE_RESTRICTION"
PUMP = "PUMP_HEAD_DEGRADATION"
SENSOR = "SENSOR_DRIFT"
MISROUTING = "VALVE_MISROUTING"
VARIANTS: dict[str, tuple[str, ...]] = {
    LEAK: ("orifice",),
    RESTRICTION: ("restriction",),
    PUMP: ("head_scale",),
    SENSOR: ("bias", "drift", "stuck"),
    MISROUTING: ("closed_but_open", "open_but_stuck"),
}
RAMPS_S = (30.0, 300.0, 1200.0)
POSITION_VISIBLE = "position_visible"
OBSTRUCTION = "obstruction"
RESTRICTION_MODES = (POSITION_VISIBLE, OBSTRUCTION)
SCHEMA_VERSION = "0.7.0"


@dataclass(frozen=True)
class FaultSpec:
    fault_type: str
    variant: str
    asset_id: str
    onset_s: float
    ramp_s: float | None  # None: a step (sensor faults only)
    magnitude: float
    position: float | None = None  # fraction along the edge (leak)
    discharge_coefficient: float | None = None  # leak
    peak_severity: float = 1.0
    fault_mode: str | None = None  # restriction only: position_visible or obstruction (D74)

    def severity(self, t: float) -> float:
        """Severity in [0, 1] at simulation time ``t``."""
        if t < self.onset_s:
            return 0.0
        if self.ramp_s is None:
            return self.peak_severity
        return self.peak_severity * min((t - self.onset_s) / self.ramp_s, 1.0)

    def knots(self) -> list[list[float]]:
        """Severity trajectory as ``(seconds since onset, severity)`` knots."""
        if self.ramp_s is None:
            return [[0.0, self.peak_severity]]
        return [[0.0, 0.0], [self.ramp_s, self.peak_severity]]

    def knot_times_s(self) -> tuple[float, ...]:
        """Absolute times at which the severity trajectory changes slope."""
        if self.ramp_s is None:
            return (self.onset_s,)
        return (self.onset_s, self.onset_s + self.ramp_s)

    def as_record(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "dataset": "fault_spec",
            "fault_type": self.fault_type,
            "variant": self.variant,
            "asset_id": self.asset_id,
            "onset_s": self.onset_s,
            "ramp_s": self.ramp_s,
            "magnitude": self.magnitude,
            "position": self.position,
            "discharge_coefficient": self.discharge_coefficient,
            "peak_severity": self.peak_severity,
            "fault_mode": self.fault_mode,
            "hidden": True,
        }


def from_record(record: Mapping[str, Any]) -> FaultSpec:
    """Validate a specification record against the schema and build the specification."""
    validate("fault_spec", record)
    return FaultSpec(
        fault_type=record["fault_type"],
        variant=record["variant"],
        asset_id=record["asset_id"],
        onset_s=float(record["onset_s"]),
        ramp_s=None if record["ramp_s"] is None else float(record["ramp_s"]),
        magnitude=float(record["magnitude"]),
        position=None if record["position"] is None else float(record["position"]),
        discharge_coefficient=(
            None
            if record["discharge_coefficient"] is None
            else float(record["discharge_coefficient"])
        ),
        peak_severity=float(record["peak_severity"]),
        fault_mode=record["fault_mode"],
    )

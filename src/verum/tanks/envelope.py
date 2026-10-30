"""Level envelope classification and the response-headroom screen.

After the independent high-high level, the worst-case inflow for the response time plus a residual
delivery raises the level on the floating branch by (Q t + V_post) / A + dh, and this must fit
between the high-high level and the critical level. No outflow credit is taken. It is a design
screen and not an API equation or a setpoint. Level classes use closed lower bounds, so a level
exactly at a threshold is in the higher class.
"""

from __future__ import annotations

from dataclasses import dataclass

from verum.contracts.topology import Tank
from verum.params import ParamValue
from verum.tanks.geometry import TankGeometry

LEVEL_CLASSES = (
    "below_minimum",
    "normal",
    "above_working_maximum",
    "high_alarm",
    "high_high",
    "critical",
)


@dataclass(frozen=True)
class LevelEnvelope:
    """Level thresholds of one tank, in metres."""

    minimum_m: float
    working_maximum_m: float
    high_alarm_m: float
    high_high_m: float
    critical_m: float

    def __post_init__(self) -> None:
        ordered = (
            self.minimum_m,
            self.working_maximum_m,
            self.high_alarm_m,
            self.high_high_m,
            self.critical_m,
        )
        if list(ordered) != sorted(set(ordered)):
            raise ValueError("level thresholds must be strictly increasing")

    @classmethod
    def from_tank(cls, tank: Tank) -> LevelEnvelope:
        d = tank.dimensions_m
        return cls(
            minimum_m=d["normal_min_level_m"],
            working_maximum_m=d["normal_max_level_m"],
            high_alarm_m=d["high_alarm_m"],
            high_high_m=d["independent_high_high_m"],
            critical_m=d["critical_model_limit_m"],
        )

    def classify(self, level_m: float) -> str:
        """Class of a level; see ``LEVEL_CLASSES``."""
        if level_m < self.minimum_m:
            return "below_minimum"
        if level_m <= self.working_maximum_m:
            return "normal"
        if level_m < self.high_alarm_m:
            return "above_working_maximum"
        if level_m < self.high_high_m:
            return "high_alarm"
        if level_m < self.critical_m:
            return "high_high"
        return "critical"

    @property
    def available_headroom_m(self) -> float:
        """Distance from the high-high level to the critical level."""
        return self.critical_m - self.high_high_m


@dataclass(frozen=True)
class HeadroomResult:
    """Outcome of one headroom screen."""

    required_rise_m: float
    required_height_m: float
    available_m: float
    margin_m: float

    @property
    def passes(self) -> bool:
        return self.margin_m >= 0


@dataclass(frozen=True)
class HeadroomScreen:
    """Screen parameters bound to a geometry and an envelope."""

    geometry: TankGeometry
    envelope: LevelEnvelope
    residual_delivery_m3: float
    level_allowance_m: float

    @classmethod
    def from_params(
        cls,
        geometry: TankGeometry,
        envelope: LevelEnvelope,
        residual_delivery: ParamValue,
        level_allowance: ParamValue,
    ) -> HeadroomScreen:
        return cls(geometry, envelope, residual_delivery.value, level_allowance.value)

    def evaluate(self, flow_m3h: float, duration_s: float) -> HeadroomResult:
        """Screen a worst-case inflow held for ``duration_s`` after the trip level."""
        if flow_m3h < 0 or duration_s < 0:
            raise ValueError("flow and duration must not be negative")
        volume = flow_m3h * duration_s / 3600.0 + self.residual_delivery_m3
        rise = volume / self.geometry.area_m2 + self.level_allowance_m
        available = self.envelope.available_headroom_m
        return HeadroomResult(
            required_rise_m=rise,
            required_height_m=self.envelope.high_high_m + rise,
            available_m=available,
            margin_m=available - rise,
        )

    def limiting_flow_m3h(self, duration_s: float) -> float:
        """Largest inflow that still passes for ``duration_s``."""
        if duration_s <= 0:
            raise ValueError("duration must be positive")
        spare_volume = (
            self.envelope.available_headroom_m - self.level_allowance_m
        ) * self.geometry.area_m2 - self.residual_delivery_m3
        return spare_volume / duration_s * 3600.0

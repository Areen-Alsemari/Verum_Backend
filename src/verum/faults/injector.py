"""The fault set of an episode: what each fault does to the plant and to the sensor chain.

The injector acts only through physical parameters: a leak sink (area), the actual opening of a
valve (the command is untouched), the head scale of the pump curve, and, for sensor faults, the
reading in the sensor chain. It reads and writes no state. Everything is a pure function of time and
of the specifications, so a restarted engine continues exactly. A fault of severity 0 changes no
number, which the equivalence tests check bit for bit. A restriction in obstruction mode changes the
opening that sets the loss but not the stem position the open contact reads.

See D60 to D65 and D74.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from verum.contracts.errors import ContractError
from verum.faults import spec as fs
from verum.hydraulics.leaks import LeakInput


@dataclass(frozen=True)
class ValveFault:
    """Actual opening of a valve under a restriction or a misrouting (decisions D61 and D64)."""

    spec: fs.FaultSpec

    def __post_init__(self) -> None:
        if self.spec.fault_type == fs.RESTRICTION and self.spec.fault_mode not in (
            fs.RESTRICTION_MODES
        ):
            raise ContractError(
                f"restriction on {self.spec.asset_id}: the mode {self.spec.fault_mode!r} is not "
                f"one of {fs.RESTRICTION_MODES}; no mode is assumed (decision D74)"
            )

    @property
    def hides_position(self) -> bool:
        """An obstruction leaves the stem, and so the open contact, at the commanded motion."""
        return self.spec.fault_type == fs.RESTRICTION and self.spec.fault_mode == fs.OBSTRUCTION

    def apply(self, alpha: float, t: float) -> float:
        s = self.spec.severity(t)
        if self.spec.variant == "closed_but_open":
            return max(alpha, s * self.spec.magnitude)
        return min(alpha, 1.0 - s * (1.0 - self.spec.magnitude))

    def threshold_times(self, closed_alpha: float) -> tuple[float, ...]:
        """Time at which a forced-open valve leaves the closed state (the opening is linear)."""
        spec = self.spec
        if spec.variant != "closed_but_open" or spec.ramp_s is None:
            return ()
        s = closed_alpha / (spec.magnitude * spec.peak_severity) if spec.peak_severity else 2.0
        return (spec.onset_s + s * spec.ramp_s,) if s < 1.0 else ()


class SensorFaultHook:
    """Changes a reading before noise and quantisation (decision D63)."""

    def __init__(self, specs: Sequence[fs.FaultSpec], spans: Mapping[str, float]) -> None:
        self._specs = {s.asset_id: s for s in specs if s.fault_type == fs.SENSOR}
        self._spans = dict(spans)
        self._frozen: dict[str, float] = {}

    def __call__(self, tag: str, t: float, value: float) -> float:
        spec = self._specs.get(tag)
        if spec is None or t < spec.onset_s:
            return value
        if spec.variant == "stuck":
            if spec.peak_severity == 0.0:
                return value
            return self._frozen.setdefault(tag, value)
        span = self._spans[tag]
        if spec.variant == "bias":
            return value + spec.severity(t) * spec.magnitude * span
        return value + spec.peak_severity * spec.magnitude * span * (t - spec.onset_s) / 3600.0


@dataclass(frozen=True)
class FaultSet:
    specs: tuple[fs.FaultSpec, ...] = ()

    def _of(self, fault_type: str) -> list[fs.FaultSpec]:
        return [s for s in self.specs if s.fault_type == fault_type]

    def leaks(self, t: float) -> tuple[LeakInput, ...]:
        """Leaks with a positive area at time ``t``."""
        out = []
        for s in self._of(fs.LEAK):
            area = s.severity(t) * s.magnitude
            if area > 0.0:
                assert s.position is not None and s.discharge_coefficient is not None
                out.append(LeakInput(s.asset_id, s.position, area, s.discharge_coefficient))
        return tuple(out)

    def valve_fault(self, valve: str) -> ValveFault | None:
        for s in self.specs:
            if s.fault_type in (fs.RESTRICTION, fs.MISROUTING) and s.asset_id == valve:
                return ValveFault(s)
        return None

    def pump_scale(self, t: float, pump: str) -> float:
        """Head scale of the named pump at time ``t`` (1 for a pump without a fault)."""
        scale = 1.0
        for s in self._of(fs.PUMP):
            if s.asset_id == pump:
                scale *= 1.0 - s.severity(t) * (1.0 - s.magnitude)
        return scale

    def knot_times(self, closed_alpha: float) -> tuple[float, ...]:
        """Times at which a step of the engine must end: ramp ends and closure thresholds."""
        times: set[float] = set()
        for s in self.specs:
            times.update(s.knot_times_s())
            fault = self.valve_fault(s.asset_id) if s.fault_type == fs.MISROUTING else None
            if fault is not None:
                times.update(fault.threshold_times(closed_alpha))
        return tuple(sorted(times))

    def sensor_hook(self, spans: Mapping[str, float]) -> SensorFaultHook:
        return SensorFaultHook(self.specs, spans)

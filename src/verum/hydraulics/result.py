"""Immutable result of a steady-state solve.

Inputs: produced by ``HydraulicModel.solve``. Outputs: a frozen dataclass of
node heads, edge flows, end pressures, tank flows, the pump operating point and
the gate statuses.
Key assumptions:
    * Internal data. It is not part of any agent-visible interface and is not
      exposed through ``verum.api``.
    * Heads are total heads (m) relative to the site datum, with gauge pressure
      zero at the tank free surface. Pressures are *static* and in Pa gauge;
      the absolute value is ``gauge + atmosphere_pa_abs``.
    * Flow is signed along the contract edge direction (from -> to).
    * Values that could not be determined for an edge (no flow and no static
      head known) are absent from the mappings, never filled with zero.

Source: ``revised/02_hydraulic_model.md`` sections 3 and 6.2 (typed hidden
state, pressure basis).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any


def _freeze(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(value))


@dataclass(frozen=True)
class PumpPoint:
    """Operating point of the running pump."""

    pump: str
    flow_m3h: float
    head_rise_m: float
    speed_ratio: float
    reference_equivalent_flow_m3h: float
    hydraulic_power_w: float
    shaft_power_w: float
    status: str


@dataclass(frozen=True)
class PhaseGate:
    """Outcome of the phase and NPSH screen (statuses OK, SCREEN_FAILED, NPSH_MARGIN_FAILED)."""

    status: str
    scenario: str
    temperature_c: float
    vapor_pressure_pa_abs: float
    min_abs_pressure_pa: float | None
    npsha_m: float | None
    npsh3_m: float | None
    margin_ratio: float | None


@dataclass(frozen=True)
class SteadyResult:
    """All outputs of one steady solve."""

    node_heads_m: Mapping[str, float]
    edge_flows_m3s: Mapping[str, float]
    edge_end_pressures_pa_gauge: Mapping[str, tuple[float, float]]
    tap_pressures_pa_gauge: Mapping[str, float]
    tank_net_inflow_m3s: Mapping[str, float]
    pump: PumpPoint | None
    phase: PhaseGate
    source_pressure_pa_gauge: float | None
    receipt_flow_m3h: float
    receipt_clipped: bool
    node_mass_residual_kg_s: Mapping[str, float]
    gates: Mapping[str, str]
    active_edges: frozenset[str]
    atmosphere_pa_abs: float
    iterations: int
    fitting_profile: str = ""
    k_multiplier: float = 1.0
    boundary_law_coefficient_m: float = 0.0
    tap_heads_m: Mapping[str, float] = field(default_factory=dict)
    edge_heads_m: Mapping[str, float] = field(default_factory=dict)
    dead_edges: frozenset[str] = frozenset()
    dead_leg_gaps_m: Mapping[str, float] = field(default_factory=dict)
    leak_flows_m3s: Mapping[str, float] = field(default_factory=dict)
    leak_pressures_pa_gauge: Mapping[str, float] = field(default_factory=dict)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for name in (
            "node_heads_m",
            "edge_flows_m3s",
            "edge_end_pressures_pa_gauge",
            "tap_pressures_pa_gauge",
            "tank_net_inflow_m3s",
            "tap_heads_m",
            "edge_heads_m",
            "dead_leg_gaps_m",
            "leak_flows_m3s",
            "leak_pressures_pa_gauge",
            "node_mass_residual_kg_s",
            "gates",
        ):
            object.__setattr__(self, name, _freeze(getattr(self, name)))

    def to_abs(self, gauge_pa: float) -> float:
        """Convert a gauge pressure of this result to absolute."""
        return gauge_pa + self.atmosphere_pa_abs

    @property
    def max_mass_residual_kg_s(self) -> float:
        return max((abs(v) for v in self.node_mass_residual_kg_s.values()), default=0.0)

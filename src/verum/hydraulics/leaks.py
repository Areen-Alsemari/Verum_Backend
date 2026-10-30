"""Pipe leak element: a sharp-edged orifice to the atmosphere at a point of an edge.

Inputs: a ``LeakInput`` (edge, fraction along the edge, area, discharge coefficient). Outputs: the
flow law the network solver uses for the leak and the error types of an invalid leak.
Key assumptions:
    * ``Q = Cd A sqrt(2 g (H - z))`` with ``H`` the total head of the leak node and ``z`` the
      elevation of the leak point; this is ``Cd A sqrt(2 p / rho)`` with ``p = rho g (H - z)``,
      the gauge pressure from the total head (the velocity head is neglected, a limit stated in
      ``docs/fault_models.md``).
    * Outward flow only: for ``H <= z`` the flow is zero. Whether a leak at that pressure is
      valid is decided by the caller (decision D10: above 10 kPa gauge).
    * No flashing and no two-phase flow.

Source: ``docs/design_decisions.md`` D10 and D60; ``docs/fault_models.md``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from verum.hydraulics.errors import HydraulicsError
from verum.hydraulics.solver import SLOPE_FLOOR, FlowLaw


class LeakError(HydraulicsError):
    """A leak cannot be placed (its edge carries no determined pressure) or is not valid."""


@dataclass(frozen=True)
class LeakInput:
    edge_id: str
    fraction: float
    area_m2: float
    discharge_coefficient: float

    def coefficient(self, gravity: float) -> float:
        """``Cd A sqrt(2 g)``: the flow per square root of the pressure head."""
        return self.discharge_coefficient * self.area_m2 * math.sqrt(2.0 * gravity)


@dataclass(frozen=True)
class OrificeLaw(FlowLaw):
    """Flow of the orifice as a function of ``delta = H - z`` (m)."""

    coefficient: float

    def flow(self, delta: float) -> float:
        return self.coefficient * math.sqrt(delta) if delta > 0.0 else 0.0

    def slope(self, delta: float) -> float:
        if delta <= 0.0:
            return SLOPE_FLOOR
        return self.coefficient / (2.0 * math.sqrt(max(delta, 1e-6)))

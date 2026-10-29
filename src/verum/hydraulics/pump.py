"""Pump element: synthetic fixed-speed curve and the interface the solver uses.

Inputs: the curve parameters (shutoff head, curve coefficient, reference flow,
maximum flow, efficiency) as read from configuration. Outputs: flow as a
function of the head difference across the pump, domain checks and power.
Key assumptions:
    * Curve: ``H(Q) = H0 s^2 - k (Q / Q_ref)^2`` with s = 1 in this phase. The
      curve is synthetic and is not a manufacturer curve.
    * The domain is ``0 <= Q / s <= Q_max``. A solution outside it is rejected
      by the caller, never extrapolated.
    * The element is one-way: flow is zero when the head the pump must add
      reaches the shutoff head.
    * ``PumpElement`` is a structural interface so that tests can supply a
      reference-case variable-speed pump; production code only provides the
      fixed-speed pump.
    * Power uses a constant efficiency (a simulation selection).

Source: ``revised/02_hydraulic_model.md`` section 3.2; ``docs/design_decisions.md``
D2 (fixed speed).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol


class PumpElement(Protocol):
    """What the network solver needs from a pump."""

    @property
    def shutoff_head_m(self) -> float: ...

    @property
    def speed_ratio(self) -> float: ...

    def flow_m3s(self, delta_m: float) -> float:
        """Flow for ``delta = H_inlet - H_outlet`` (negative of the head rise)."""
        ...

    def slope(self, delta_m: float) -> float:
        """Derivative of the flow with respect to ``delta``."""
        ...

    def head_rise_m(self, flow_m3h: float) -> float: ...

    def in_domain(self, flow_m3h: float) -> bool: ...


@dataclass(frozen=True)
class FixedSpeedPump:
    """The synthetic curve at the fixed reference speed (s = 1)."""

    h0_m: float
    k_m: float
    q_ref_m3h: float
    q_max_m3h: float
    efficiency: float
    speed_ratio: float = 1.0

    def __post_init__(self) -> None:
        if self.speed_ratio != 1.0:
            raise ValueError("this phase runs the pump at the fixed reference speed")
        if not 0 < self.efficiency <= 1:
            raise ValueError("efficiency must be in (0, 1]")

    @property
    def shutoff_head_m(self) -> float:
        return self.h0_m * self.speed_ratio**2

    def head_rise_m(self, flow_m3h: float) -> float:
        return self.shutoff_head_m - self.k_m * (flow_m3h / self.q_ref_m3h) ** 2

    def flow_m3s(self, delta_m: float) -> float:
        head_rise = -delta_m
        if head_rise >= self.shutoff_head_m:
            return 0.0
        q_m3h = self.q_ref_m3h * math.sqrt((self.shutoff_head_m - head_rise) / self.k_m)
        return q_m3h / 3600.0

    def slope(self, delta_m: float) -> float:
        head_rise = -delta_m
        gap = max(self.shutoff_head_m - head_rise, 1e-9)
        return self.q_ref_m3h / 3600.0 * 0.5 / math.sqrt(self.k_m * gap)

    def in_domain(self, flow_m3h: float) -> bool:
        return 0.0 <= flow_m3h / self.speed_ratio <= self.q_max_m3h


def hydraulic_power_w(rho: float, gravity: float, flow_m3s: float, head_m: float) -> float:
    """Power delivered to the liquid: ``rho g Q H``."""
    return rho * gravity * flow_m3s * head_m


def shaft_power_w(hydraulic_w: float, efficiency: float) -> float:
    """Shaft power at a constant efficiency."""
    return hydraulic_w / efficiency

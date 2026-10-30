"""Pump element: synthetic fixed-speed curve and the interface the solver uses.

The curve is H(Q) = H0 s^2 - k (Q / Q_ref)^2 with speed ratio s = 1, and is synthetic, not a
manufacturer curve. The domain is 0 <= Q / s <= Q_max, and a solution outside it is rejected by the
caller and never extrapolated. The element is one-way, so flow is zero when the head the pump must
add reaches the shutoff head. Power uses a constant efficiency, which is a simulation selection.

See D2.
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
        if head_rise >= self.shutoff_head_m:
            return 0.0  # flow is identically zero here, so is its derivative
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

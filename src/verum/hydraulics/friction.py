"""Darcy-Weisbach friction and head loss with signed flow.

The friction factor is 64/Re below Re 2300 and the Haaland expression above Re 4000, with a linear
blend in between that is a numerical device and not a physical model. The head loss uses the
magnitude of the velocity and carries the sign of the flow, so reverse flow is represented and never
clipped. A local loss coefficient uses the velocity in the same pipe. All quantities are in SI
units.

See D14.
"""

from __future__ import annotations

import math
from typing import Final

RE_LAMINAR: Final = 2300.0
RE_TURBULENT: Final = 4000.0


def reynolds(velocity: float, diameter: float, rho: float, mu: float) -> float:
    """Reynolds number from the velocity magnitude."""
    return rho * abs(velocity) * diameter / mu


def haaland(re: float, relative_roughness: float) -> float:
    """Haaland friction factor for turbulent flow."""
    return (-1.8 * math.log10((relative_roughness / 3.7) ** 1.11 + 6.9 / re)) ** -2


def friction_factor(re: float, relative_roughness: float) -> float:
    """Darcy friction factor per decision D14; ``re`` must be positive."""
    if re <= 0:
        raise ValueError("Reynolds number must be positive")
    if re < RE_LAMINAR:
        return 64.0 / re
    if re > RE_TURBULENT:
        return haaland(re, relative_roughness)
    laminar_end = 64.0 / RE_LAMINAR
    turbulent_start = haaland(RE_TURBULENT, relative_roughness)
    weight = (re - RE_LAMINAR) / (RE_TURBULENT - RE_LAMINAR)
    return laminar_end + weight * (turbulent_start - laminar_end)


def head_loss(
    flow_m3s: float,
    diameter: float,
    length: float,
    k_local: float,
    rho: float,
    mu: float,
    roughness: float,
    gravity: float,
) -> float:
    """Signed head loss (m): ``(f L / D + K) v |v| / (2 g)``."""
    if flow_m3s == 0.0:
        return 0.0
    velocity = flow_m3s / (math.pi * diameter**2 / 4)
    re = reynolds(velocity, diameter, rho, mu)
    f = friction_factor(re, roughness / diameter) if re > 0 else 0.0
    loss = (f * length / diameter + k_local) * velocity * abs(velocity) / (2 * gravity)
    return loss

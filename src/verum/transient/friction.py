"""Vectorised Darcy friction factor, the same law as the steady package.

The factor is 64/Re below Re 2300, Haaland above 4000, with a linear blend between, and a test
compares it with the steady version. A zero velocity gives the laminar-limit factor at a tiny
Reynolds number so that no division by zero occurs, and the loss it multiplies is zero.

See D14.
"""

from __future__ import annotations

import numpy as np

RE_LAMINAR = 2300.0
RE_TURBULENT = 4000.0
RE_FLOOR = 1.0


def darcy_factor(
    velocity: np.ndarray, diameter: np.ndarray, rho: float, mu: float, roughness: float
) -> np.ndarray:
    re = np.maximum(rho * np.abs(velocity) * diameter / mu, RE_FLOOR)
    rel = roughness / diameter

    def haaland(r: np.ndarray) -> np.ndarray:
        return (-1.8 * np.log10((rel / 3.7) ** 1.11 + 6.9 / r)) ** -2

    laminar_end = 64.0 / RE_LAMINAR
    turb_start = (-1.8 * np.log10((rel / 3.7) ** 1.11 + 6.9 / RE_TURBULENT)) ** -2
    blend = laminar_end + (re - RE_LAMINAR) / (RE_TURBULENT - RE_LAMINAR) * (
        turb_start - laminar_end
    )
    return np.where(
        re < RE_LAMINAR, 64.0 / re, np.where(re > RE_TURBULENT, haaland(np.maximum(re, 1.0)), blend)
    )

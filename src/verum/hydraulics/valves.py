"""Valve flow coefficient and loss coefficient as functions of the opening.

Kv is continuous: linear below the crossover opening, equal-percentage above, and zero at alpha = 0.
The loss coefficient is K = K_open (Kv_max / Kv)^2 at the local diameter, so K(1) = K_open and K is
infinite at alpha = 0. Below the closed threshold the caller treats the edge as closed.

See D4 and D19.
"""

from __future__ import annotations

import math


def kv_fraction(alpha: float, alpha_c: float, rangeability: float) -> float:
    """Kv(alpha) / Kv_max."""
    if not 0.0 <= alpha <= 1.0:
        raise ValueError("opening must be in [0, 1]")
    if alpha == 0.0:
        return 0.0
    if alpha <= alpha_c:
        return float(alpha / alpha_c * rangeability ** (alpha_c - 1.0))
    return float(rangeability ** (alpha - 1.0))


def loss_coefficient(alpha: float, k_open: float, alpha_c: float, rangeability: float) -> float:
    """K(alpha) = K_open (Kv_max / Kv(alpha))^2."""
    fraction = kv_fraction(alpha, alpha_c, rangeability)
    return math.inf if fraction == 0.0 else k_open / fraction**2

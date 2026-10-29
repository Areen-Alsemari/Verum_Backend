"""Valve flow coefficient and loss coefficient as functions of the opening.

Inputs: an opening fraction alpha in [0, 1] and the law parameters (alpha_c,
rangeability, full-open K). Outputs: Kv / Kv_max and the loss coefficient K(alpha).
Key assumptions:
    * Kv(alpha) is continuous: linear below alpha_c, equal-percentage above,
      ``Kv = Kv_max alpha / alpha_c R^(alpha_c - 1)`` and ``Kv = Kv_max R^(alpha - 1)``
      (decision D4 version 2.0), zero at alpha = 0.
    * The loss coefficient is ``K = K_open (Kv_max / Kv)^2`` at the local diameter
      (decision D19), so K(1) = K_open. Below the closed threshold the caller treats
      the edge as closed; this function itself returns infinity at alpha = 0.

Source: ``docs/design_decisions.md`` D4 (version 2.0) and D19.
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

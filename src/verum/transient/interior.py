"""Pipe interior update: the C+ and C- characteristics with the friction term.

Inputs: heads and flows at the old time level on all grid points and the constant per-point
arrays of the pipe each point belongs to. Outputs: the new heads and flows of interior points and
the characteristic constants of the pipe ends.
Key assumptions:
    * First-order scheme with the Courant number one on every edge: the characteristic through a
      point at the new level starts at its neighbours at the old level (decision D43).
    * C+: ``H_P = H_A + B (Q_A - Q_P) - R Q_A |Q_A|``; C-: ``H_P = H_B - B (Q_B - Q_P) +
      R Q_B |Q_B|`` with ``B = a/(g A)`` and the reach resistance
      ``R = (f dx/D + K dx/L)/(2 g A^2)``; the local loss coefficient K of the edge is spread
      evenly along it, and the friction factor is that of the steady package at the old velocity.
    * Heads are piezometric (elevation included), so no slope term appears.

Source: ``docs/design_decisions.md`` D43; Wylie and Streeter, Fluid Transients in Systems,
chapter 2.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from verum.transient.friction import darcy_factor


@dataclass(frozen=True)
class PointConstants:
    """Constants of the pipe that each grid point belongs to (arrays over all points)."""

    b: np.ndarray  # a/(g A)
    diameter: np.ndarray
    area: np.ndarray
    dx: np.ndarray
    k_per_reach: np.ndarray  # local loss coefficient of one reach
    inv_2ga2: np.ndarray
    rho: float
    mu: float
    roughness: float


def _reach_resistance(pc: PointConstants, target: np.ndarray, flow: np.ndarray) -> np.ndarray:
    d = pc.diameter[target]
    f = darcy_factor(flow / pc.area[target], d, pc.rho, pc.mu, pc.roughness)
    return (f * pc.dx[target] / d + pc.k_per_reach[target]) * pc.inv_2ga2[target]


def c_plus(
    pc: PointConstants, h: np.ndarray, q: np.ndarray, target: np.ndarray, a: np.ndarray
) -> np.ndarray:
    """C+ constant for ``target`` points from their upstream neighbours ``a``."""
    qa = q[a]
    return h[a] + pc.b[target] * qa - _reach_resistance(pc, target, qa) * qa * np.abs(qa)


def c_minus(
    pc: PointConstants, h: np.ndarray, q: np.ndarray, target: np.ndarray, b: np.ndarray
) -> np.ndarray:
    """C- constant for ``target`` points from their downstream neighbours ``b``."""
    qb = q[b]
    return h[b] - pc.b[target] * qb + _reach_resistance(pc, target, qb) * qb * np.abs(qb)


def interior_update(
    pc: PointConstants, h: np.ndarray, q: np.ndarray, interior: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """New heads and flows of the interior points."""
    cp = c_plus(pc, h, q, interior, interior - 1)
    cm = c_minus(pc, h, q, interior, interior + 1)
    bb = pc.b[interior]
    q_new = (cp - cm) / (2.0 * bb)
    return cp - bb * q_new, q_new

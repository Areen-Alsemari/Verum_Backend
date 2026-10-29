"""Independent reference calculations for the hydraulics tests.

Inputs: literal constants of the audited reference case (written out here, not
read from configuration) and path descriptions. Outputs: series-path head
losses and closed-form operating points found with ``scipy.optimize.brentq``.
Key assumptions:
    * This module does not import ``verum.hydraulics``. It solves a single
      series path (tank, suction branch, pump branch, distribution main) by a
      scalar root find, which is a different method from the node-head Newton
      solve of the package.
    * The friction law is the same Darcy-Weisbach/Haaland/laminar/blend law as
      decision D14, coded separately; agreement on the law is therefore not
      independent evidence about the law itself, only about the network solve.
    * Bore diameters, lengths, density, viscosity and pump curve are the
      audited literals.

Source: ``revised/02_hydraulic_model.md`` sections 2 and 3;
``verum_member2_verify_corrected.py`` (functions ``friction`` and ``syst``).
"""

from __future__ import annotations

import math

from scipy.optimize import brentq

RHO = 750.0
MU = 5.0e-4
G = 9.80665
EPS = 4.5e-5
D200, D250, D300 = 0.20274, 0.25446, 0.30318
Z_BOUNDARY = 0.5


def _haaland(re: float, d: float) -> float:
    return float((-1.8 * math.log10((EPS / d / 3.7) ** 1.11 + 6.9 / re)) ** -2)


def friction(re: float, d: float) -> float:
    if re < 2300:
        return 64 / re
    if re > 4000:
        return _haaland(re, d)
    f_lam, f_turb = 64 / 2300, _haaland(4000, d)
    return f_lam + (f_turb - f_lam) * (re - 2300) / 1700


def loss(q: float, d: float, length: float, k: float = 0.0) -> float:
    """Head loss (m) for a flow magnitude q (m3/s)."""
    if q == 0:
        return 0.0
    v = q / (math.pi * d * d / 4)
    re = RHO * v * d / MU
    return (friction(re, d) * length / d + k) * v * v / (2 * G)


def path_loss(q: float, segments: list[tuple[float, float, float]]) -> float:
    return sum(loss(q, d, length, k) for d, length, k in segments)


SUCTION_LENGTH = {"TK-101": 60.0, "TK-102": 90.0, "TK-103": 120.0}


def delivery_segments(tank: str) -> list[tuple[float, float, float]]:
    """Pipe-only series path: suction branch, header, pump branch, distribution main."""
    return [
        (D200, SUCTION_LENGTH[tank], 0.0),
        (D250, 35.0, 0.0),
        (D200, 20.0, 0.0),
        (D200, 250.0, 0.0),
    ]


def tank2_reference_fittings_segments() -> list[tuple[float, float, float]]:
    """TK-102 path with the reference fittings, counted by hand from the polylines.

    Suction route: 3 bends x 0.3 + tank outlet 0.5 + XV-S102 0.1 = 1.5.
    Pump branch A: 2 bends x 0.3 + XV-PAI 0.1 + check valve 2.0 + XV-PAO 0.1 = 2.8.
    Distribution main: 1 bend x 0.3 + delivery meter 1.0 = 1.3. The header has none.
    """
    return [(D200, 90.0, 1.5), (D250, 35.0, 0.0), (D200, 20.0, 2.8), (D200, 250.0, 1.3)]


def required_head(
    q: float,
    level: float,
    c: float,
    reservoir_pa: float,
    segments: list[tuple[float, float, float]],
) -> float:
    """Head the pump must add at flow q (m3/s) for a tank level."""
    h_res = Z_BOUNDARY + reservoir_pa / (RHO * G)
    return (h_res - level) + c * (q * 3600 / 300) ** 2 + path_loss(q, segments)


def pump_head(q: float, s: float = 1.0) -> float:
    return 54.0 * s * s - 12.0 * (q * 3600 / 300) ** 2


def operating_flow_m3h(
    level: float,
    c: float,
    segments: list[tuple[float, float, float]],
    s: float = 1.0,
    reservoir_pa: float = 200000.0,
) -> float:
    """Pump/system intersection by a scalar root find; the curve is not domain-limited here."""

    def f(q: float) -> float:
        return pump_head(q, s) - required_head(q, level, c, reservoir_pa, segments)

    return float(brentq(f, 1e-6, 0.5, xtol=1e-14)) * 3600


def speed_for_flow(level: float, q_m3h: float, segments: list[tuple[float, float, float]]) -> float:
    """Speed ratio that gives q_m3h with the fixed 2 barg boundary and no boundary law."""
    q = q_m3h / 3600
    need = required_head(q, level, 0.0, 200000.0, segments)
    return math.sqrt((need + 12 * (q_m3h / 300) ** 2) / 54.0)

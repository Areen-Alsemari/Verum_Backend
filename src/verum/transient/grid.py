"""Reach grid and per-edge wave-speed adjustment (decision D43).

Inputs: the edges (anything with an id, length and bore), the screening wave speeds by
nominal size and the time step.
Outputs: for each edge the number of reaches, the adjusted wave speed, the reach length and the
adjustment in percent; the maximum adjustment.
Key assumptions:
    * One time step ``dt`` for all edges. Each edge has ``N = max(1, round(L / (a dt)))`` reaches
      and its wave speed is adjusted to ``a' = L / (N dt)`` so that the Courant number is
      exactly one on every edge. ``dt = 0.923 ms`` keeps the adjustment below 0.53 percent.
    * The screening speeds are those of the audited package (1089.2, 1082.8 and 1078.2 m/s for
      DN200, DN250 and DN300, restraint factor psi = 1, a screening value). A restraint factor
      or a bulk modulus other than the reference scales them with the thin-wall relation
      ``a = sqrt((K / rho) / (1 + (K / K0) psi c_i))``, where ``c_i`` is fixed by the screening
      speed of the size at K0 = 1e9 Pa and psi = 1.

Source: ``docs/design_decisions.md`` D43; ``revised/05_simulation_validation_dataset.md``
PAR-PIP-007 and section 4.2.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verum.contracts.paths import config_dir

DT_S = 0.000923
K_REFERENCE = 1.0e9
RHO_REFERENCE = 750.0


@dataclass(frozen=True)
class EdgeGrid:
    edge_id: str
    length_m: float
    diameter_m: float
    area_m2: float
    wave_speed_screen_m_s: float
    reaches: int
    wave_speed_m_s: float
    reach_length_m: float
    adjustment_percent: float


def dn_of(diameter_m: float) -> int:
    return int(round(diameter_m * 1000.0 / 50.0)) * 50


def load_wave_speeds(directory: Path | None = None) -> dict[int, float]:
    """Screening wave speeds by nominal size from ``config/sim.json``."""
    raw = json.loads(((directory or config_dir()) / "sim.json").read_text(encoding="utf-8"))
    p = raw["parameters"]
    return {200: p["wave_speed_dn200_m_s"]["value"], 250: p["wave_speed_dn250_m_s"]["value"],
            300: p["wave_speed_dn300_m_s"]["value"]}  # fmt: skip


def scaled_speeds(
    speeds: dict[int, float], psi: float = 1.0, bulk_modulus_pa: float = K_REFERENCE,
    rho: float = RHO_REFERENCE,
) -> dict[int, float]:  # fmt: skip
    """Screening speeds for another restraint factor or bulk modulus (thin-wall relation)."""
    out = {}
    for dn, a in speeds.items():
        c = (K_REFERENCE / rho) / a**2 - 1.0
        out[dn] = math.sqrt(
            (bulk_modulus_pa / rho) / (1.0 + (bulk_modulus_pa / K_REFERENCE) * psi * c)
        )
    return out


def build_grid(edges: Sequence[Any], speeds: dict[int, float], dt: float = DT_S) -> list[EdgeGrid]:
    grid = []
    for e in edges:
        a = speeds[dn_of(e.inner_diameter_m)]
        n = max(1, round(e.length_m / (a * dt)))
        a_adj = e.length_m / (n * dt)
        grid.append(
            EdgeGrid(
                e.edge_id, e.length_m, e.inner_diameter_m, math.pi * e.inner_diameter_m**2 / 4,
                a, n, a_adj, e.length_m / n, 100.0 * (a_adj / a - 1.0),
            )
        )  # fmt: skip
    return grid


def max_adjustment_percent(grid: list[EdgeGrid]) -> float:
    return max(abs(g.adjustment_percent) for g in grid)

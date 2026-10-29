"""Diagnostics of a transient run: minimum pressure, Courant number, mass ledger, phase windows.

Inputs: the state arrays at each step. Outputs: the minimum head per grid point, the intervals in
which any point is at or below the vapor pressure, the largest departure of the Courant number
from one, and the mass ledger.
Key assumptions:
    * The Courant number of an edge is ``a' dt/dx`` and is one by construction after the
      wave-speed adjustment; the diagnostic records its largest departure.
    * Phase window (decision D45): a step in which any point has an absolute pressure at or below
      the vapor pressure of the episode opens an interval; nothing from it is usable. Pressures are
      never clipped.
    * Ledger: ``inflow - outflow - leak - d(storage) = residual`` with the elastic storage of the
      pipes ``sum A dx g/a^2 (H - H_0)`` (trapezoid weights at the ends) and the liquid
      leaving through the tank and reservoir ends counted as outflow.

Source: ``docs/design_decisions.md`` D43 and D45.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Ledger:
    inflow_m3: float = 0.0
    outflow_m3: float = 0.0
    leak_m3: float = 0.0
    storage_m3: float = 0.0

    @property
    def residual_m3(self) -> float:
        return self.inflow_m3 - self.outflow_m3 - self.leak_m3 - self.storage_m3


@dataclass
class PhaseWindows:
    windows: list[tuple[float, float]] = field(default_factory=list)
    _open: float | None = None

    def update(self, t: float, below: bool) -> None:
        if below and self._open is None:
            self._open = t
        elif not below and self._open is not None:
            self.windows.append((self._open, t))
            self._open = None

    def close(self, t: float) -> None:
        if self._open is not None:
            self.windows.append((self._open, t))
            self._open = None

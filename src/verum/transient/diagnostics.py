"""Diagnostics of a transient run: minimum pressure, Courant number, mass ledger, phase windows.

The Courant number of an edge is one by construction after the wave-speed adjustment, and the
diagnostic records its largest departure. A step in which any point is at or below the vapor
pressure opens a phase window, and nothing from it is usable. Pressures are never clipped. The
ledger is inflow - outflow - leak - d(storage) = residual, with the elastic storage of the pipes and
the liquid leaving through tank and reservoir ends counted as outflow.

See D43 and D45.
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

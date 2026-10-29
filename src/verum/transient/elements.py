"""Series elements between two pipe ends: valve, pump, check valve, closed element.

Inputs: for the two ends of an element the characteristic constants and conductances, and the
element's law. Outputs: the flow through the element, positive from the first end to the second.
Key assumptions:
    * Valve (decisions D4 and D19): an extra resistance ``K2 = (K(alpha) - K_open)/(2 g A^2)``
      so that the head drops by ``K2 Q|Q|``; a closed valve (alpha at or below the closed
      threshold) is a zero-flow element on both sides.
    * Pump (decision D44): a quasi-steady curve ``h = H0 - k (Q/Q_ref)^2`` between the inlet and
      the outlet node, no inertia (decision D6). A stopped pump is a resistance with the same
      quadratic coefficient and no shutoff head (a modelling choice, documented), so reverse flow
      through it is possible until a check valve closes.
    * Check valve (decision D44): open it is a plain series node; it closes a finite delay after
      the flow first reverses, the reverse volume that passes meanwhile is accounted, and it
      reopens when the upstream total head exceeds the downstream one.
    * All flows follow from ``B_s Q + K2 Q|Q| = W + S`` with ``B_s = B_1 + B_2`` and
      ``W = D_1 - D_2``; ``S`` is the pump shutoff head.

Source: ``docs/design_decisions.md`` D4, D6, D19 and D44.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def series_flow(
    bs: np.ndarray, w: np.ndarray, shutoff: np.ndarray, k2: np.ndarray, closed: np.ndarray
) -> np.ndarray:
    """Flow through each series element (vectorised); closed elements carry none."""
    rhs = w + shutoff
    safe = np.where(k2 > 0.0, k2, 1.0)
    quad = np.sign(rhs) * (-bs + np.sqrt(bs**2 + 4.0 * safe * np.abs(rhs))) / (2.0 * safe)
    q = np.where(k2 > 0.0, quad, rhs / bs)
    return np.where(closed, 0.0, q)


@dataclass
class CheckValve:
    """State of one check valve (decision D44)."""

    delay_s: float
    open: bool = True
    reverse_time_s: float = 0.0
    reverse_volume_m3: float = 0.0
    closed_at_s: float | None = None

    def update(self, free_flow: float, dt: float, t: float) -> bool:
        """Advance the state with the flow the open valve would pass; returns True if open."""
        if self.open:
            if free_flow < 0.0:
                self.reverse_time_s += dt
                self.reverse_volume_m3 += -free_flow * dt
                if self.reverse_time_s >= self.delay_s:
                    self.open, self.closed_at_s = False, t
            else:
                self.reverse_time_s = 0.0
        elif free_flow > 0.0:
            self.open, self.reverse_time_s = True, 0.0
        return self.open

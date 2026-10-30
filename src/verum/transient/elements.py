"""Series elements between two pipe ends: valve, pump, check valve, closed element.

- A valve adds a resistance K2 = (K(alpha) - K_open) / (2 g A^2), and a closed valve is a zero-flow
  element.
- A pump follows a quasi-steady curve h = H0 - k (Q / Q_ref)^2 with no inertia. A stopped pump is a
  resistance with the same quadratic coefficient and no shutoff head, so reverse flow through it is
  possible until a check valve closes.
- A check valve closes a finite delay after the flow first reverses, accounts for the reverse volume
  that passes meanwhile, and reopens when the upstream total head exceeds the downstream one.

The flow is positive from the first end to the second.

See D4, D6, D19 and D44.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def series_flow(
    bs: np.ndarray, w: np.ndarray, shutoff: np.ndarray, k2: np.ndarray, closed: np.ndarray
) -> np.ndarray:
    """Flow through each series element (vectorised); closed elements carry none."""
    rhs = w + shutoff
    # the rationalised root 2 |rhs| / (bs + sqrt(bs^2 + 4 k2 |rhs|)) stays exact as k2 -> 0;
    # the textbook form loses every digit there and returned zero flow for k2 ~ 1e-16
    q = np.sign(rhs) * 2.0 * np.abs(rhs) / (bs + np.sqrt(bs**2 + 4.0 * k2 * np.abs(rhs)))
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
                if self.reverse_time_s >= self.delay_s:
                    # the step that closes the valve passes nothing, so it adds no reverse volume
                    self.open, self.closed_at_s = False, t
                else:
                    self.reverse_volume_m3 += -free_flow * dt
            else:
                self.reverse_time_s = 0.0
        elif free_flow > 0.0:
            self.open, self.reverse_time_s = True, 0.0
        return self.open

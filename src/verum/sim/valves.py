"""Valve actuator: commanded state, actual position and physical closure.

Inputs: valve orders and times. Outputs: the actual opening at any time, and the
times at which the valve starts and stops moving or crosses the closed threshold.
Key assumptions:
    * The opening alpha moves linearly at ``1 / stroke`` per second towards the
      target (decision D19). A new order during a stroke starts from the actual
      position at that instant.
    * Three records are kept apart: the commanded state (an order), the actual
      position (alpha) and the physical closure (alpha at or below the closed
      threshold, 0.001).
    * The position is a pure function of time between orders, so the engine can
      evaluate it at any stage time without stepping the actuator.

Source: ``docs/design_decisions.md`` D4 (version 2.0) and D19.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Valve:
    name: str
    stroke_s: float
    closed_alpha: float
    position0: float
    t0: float
    target: float
    commanded_open: bool

    def alpha(self, t: float) -> float:
        """Actual opening at time ``t``."""
        travelled = max(t - self.t0, 0.0) / self.stroke_s
        distance = abs(self.target - self.position0)
        step = min(travelled, distance)
        return self.position0 + step if self.target > self.position0 else self.position0 - step

    def is_physically_closed(self, t: float) -> bool:
        # The tolerance absorbs the last bit of the linear motion at the threshold time.
        return self.alpha(t) <= self.closed_alpha + 1e-12

    def is_moving(self, t: float) -> bool:
        return self.alpha(t) != self.target

    def motion_end_s(self) -> float:
        return self.t0 + abs(self.target - self.position0) * self.stroke_s

    def threshold_time_s(self) -> float | None:
        """Time at which a moving valve crosses the closed threshold, if it does."""
        low, high = sorted((self.position0, self.target))
        if not low < self.closed_alpha < high:
            return None
        return self.t0 + abs(self.closed_alpha - self.position0) * self.stroke_s

    def order(self, is_open: bool, t: float) -> bool:
        """Apply an order at time ``t``; returns True if the valve starts moving."""
        current = self.alpha(t)
        self.position0, self.t0 = current, t
        self.target = 1.0 if is_open else 0.0
        self.commanded_open = is_open
        return current != self.target


def make_valve(name: str, stroke_s: float, closed_alpha: float, is_open: bool) -> Valve:
    alpha = 1.0 if is_open else 0.0
    return Valve(name, stroke_s, closed_alpha, alpha, 0.0, alpha, is_open)

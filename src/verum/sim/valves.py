"""Valve actuator: commanded state, actual position and physical closure.

The opening moves linearly at 1 / stroke per second towards its target, and a new order during a
stroke starts from the actual position at that instant. The commanded state, the actual position and
the physical closure (an opening of 0.001 or less) are kept apart. A fault may change the actual
opening through a ceiling or a floor, but not the command, the stroke or the actuator position.
Between orders the position is a pure function of time.

See D19 and D74.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class OpeningModifier(Protocol):
    """A fault that changes the actual opening and nothing else (decisions D61 and D64)."""

    def apply(self, alpha: float, t: float) -> float: ...

    @property
    def hides_position(self) -> bool: ...


@dataclass
class Valve:
    name: str
    stroke_s: float
    closed_alpha: float
    position0: float
    t0: float
    target: float
    commanded_open: bool
    fault: OpeningModifier | None = None

    def motion_alpha(self, t: float) -> float:
        """Opening the actuator would have at time ``t`` without a fault (the commanded motion)."""
        travelled = max(t - self.t0, 0.0) / self.stroke_s
        distance = abs(self.target - self.position0)
        step = min(travelled, distance)
        return self.position0 + step if self.target > self.position0 else self.position0 - step

    def alpha(self, t: float) -> float:
        """Actual opening at time ``t``: the commanded motion, changed by a fault if any."""
        alpha = self.motion_alpha(t)
        return alpha if self.fault is None else self.fault.apply(alpha, t)

    def contact_alpha(self, t: float) -> float | None:
        """Stem position the open contact reads when a fault hides it from the opening that sets the
        loss; None when the two are the same (D74).
        """
        if self.fault is not None and self.fault.hides_position:
            return self.motion_alpha(t)
        return None

    def is_physically_closed(self, t: float) -> bool:
        # The tolerance absorbs the last bit of the linear motion at the threshold time.
        return self.alpha(t) <= self.closed_alpha + 1e-12

    def is_moving(self, t: float) -> bool:
        return self.motion_alpha(t) != self.target

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
        current = self.motion_alpha(t)  # the actuator continues from its own position
        self.position0, self.t0 = current, t
        self.target = 1.0 if is_open else 0.0
        self.commanded_open = is_open
        return current != self.target


def make_valve(name: str, stroke_s: float, closed_alpha: float, is_open: bool) -> Valve:
    alpha = 1.0 if is_open else 0.0
    return Valve(name, stroke_s, closed_alpha, alpha, 0.0, alpha, is_open)

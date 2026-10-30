"""Downstream demand factor: an Ornstein-Uhlenbeck process in the logarithm.

The factor multiplies the boundary-law coefficient of the delivery. Its logarithm is stationary with
standard deviation sigma and correlation time tau, drawn on a one-second grid with the exact
transition, and is linear between grid points. The factor is clipped to a configured range and is
exactly one without a demand process. The whole path is drawn from the named stream "demand" when
the process is created, so a restart reproduces it and no other stream is touched.

See D23.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.signal import lfilter

from verum.rng import RandomStreams

STREAM = "demand"
GRID_S = 1.0


class DemandProcess:
    def __init__(
        self,
        enabled: bool,
        streams: RandomStreams,
        duration_s: float,
        sigma: float,
        tau_s: float,
        f_min: float,
        f_max: float,
    ) -> None:
        self.enabled, self.f_min, self.f_max = enabled, f_min, f_max
        self.log_path = np.zeros(int(math.ceil(duration_s / GRID_S)) + 2)
        if enabled:
            self.log_path = self._draw(streams, len(self.log_path), sigma, tau_s)

    @staticmethod
    def _draw(streams: RandomStreams, n: int, sigma: float, tau_s: float) -> np.ndarray:
        rng = streams.stream(STREAM)
        phi = math.exp(-GRID_S / tau_s)
        noise = rng.standard_normal(n)
        scale = sigma * math.sqrt(1.0 - phi * phi)
        first = sigma * noise[0]
        rest, _ = lfilter([scale], [1.0, -phi], noise[1:], zi=[phi * first])
        return np.concatenate(([first], rest))

    def factor(self, t: float) -> float:
        if not self.enabled:
            return 1.0
        s = max(t, 0.0) / GRID_S
        k = min(int(s), len(self.log_path) - 2)
        x = self.log_path[k] + (s - k) * (self.log_path[k + 1] - self.log_path[k])
        return min(max(math.exp(x), self.f_min), self.f_max)

    def unclipped_log(self, t: float) -> float:
        s = max(t, 0.0) / GRID_S
        k = min(int(s), len(self.log_path) - 2)
        return float(self.log_path[k] + (s - k) * (self.log_path[k + 1] - self.log_path[k]))

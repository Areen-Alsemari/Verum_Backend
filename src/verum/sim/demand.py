"""Downstream demand factor: an Ornstein-Uhlenbeck process in the logarithm.

Inputs: the master seed, the duration, the process parameters and, optionally, the
named stream. Outputs: ``f_d`` at any time, the factor that multiplies the
boundary-law coefficient of the delivery (decision D23).
Key assumptions:
    * ``log f_d`` is stationary with standard deviation ``sigma`` and correlation time
      ``tau``; it is drawn on the grid of one second with the exact transition
      ``X(k+1) = phi X(k) + sigma sqrt(1 - phi^2) xi``, ``phi = exp(-dt / tau)``.
    * The draws come from the named stream ``demand`` only. The whole path is drawn when
      the process is created, so a restart reproduces it and no other stream is touched.
    * Between grid points ``log f_d`` is linear; the factor is clipped to
      ``[f_min, f_max]``. Without a demand process the factor is exactly one.

Source: ``docs/design_decisions.md`` D23.
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

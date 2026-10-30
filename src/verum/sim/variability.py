"""Healthy-variability profile v2: demand regimes and a receipt set-point process.

Inputs: the master seed, the configuration (decision D73) and, for each regime, a gate callback
that reports why a candidate regime value is not acceptable at the present state. Outputs: the
regime-valued downstream factor, the receipt set-point deviation, and the records of every regime
drawn and every candidate redrawn.
Key assumptions:
    * A regime holds a log-uniform factor for a dwell drawn uniformly, and is entered by a linear
      ramp from the previous value; the first regime has no ramp. The downstream factor is the
      regime value times the Ornstein-Uhlenbeck factor of decision D23, floored at the lower bound
      that keeps the pump inside its curve with a margin (``tools/regime_bound.py``).
    * Regime ``i`` is drawn from the named stream ``demand_regime/i``, all of its candidates in
      order, so the draw is a function of the seed and the index only and no generator state has
      to be saved in a checkpoint; the accepted regimes and the redraws live in the engine state.
    * A regime is drawn when time first reaches the end of the previous plateau, and the gate is
      asked at the state of that moment with the delivering tank lowered by an allowance that
      covers the level change over the ramp.
    * The receipt set-point deviation is an Ornstein-Uhlenbeck process on the named stream
      ``receipt_setpoint``, a fraction of the set-point, clipped; it is drawn for the whole
      duration when the engine is created. The nominal set-points are screened for headroom at
      the largest clipped value before the run.
    * ``off`` and ``v1`` are the profiles that existed before this module; they do not use it.

Source: ``docs/design_decisions.md`` D23, D73.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.signal import lfilter

from verum.contracts.errors import ContractError
from verum.rng import RandomStreams
from verum.sim.config import SimConfig
from verum.sim.demand import DemandProcess

PROFILES = ("off", "v1", "v2")
REGIME_STREAM = "demand_regime"
RECEIPT_STREAM = "receipt_setpoint"
GRID_S = 1.0

Gate = Callable[[float], str | None]


def resolve_profile(declared: str | None, demand_process: bool) -> str:
    """The profile of a scenario file; files without the key keep their earlier meaning."""
    if declared is None:
        return "v1" if demand_process else "off"
    if declared not in PROFILES:
        raise ContractError(f"scenario: variability_profile must be one of {PROFILES}")
    if (declared == "off") == demand_process:
        raise ContractError(
            f"scenario: variability_profile {declared!r} does not agree with "
            f"demand_process={demand_process}"
        )
    return declared


@dataclass(frozen=True)
class Regime:
    index: int
    t_start_s: float
    value: float
    dwell_s: float
    ramp_s: float
    draws: int

    @property
    def plateau_start_s(self) -> float:
        return self.t_start_s + self.ramp_s

    @property
    def plateau_end_s(self) -> float:
        return self.plateau_start_s + self.dwell_s

    def as_record(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "t_start_s": self.t_start_s,
            "plateau_start_s": self.plateau_start_s,
            "plateau_end_s": self.plateau_end_s,
            "value": self.value,
            "dwell_s": self.dwell_s,
            "draws": self.draws,
        }


@dataclass(frozen=True)
class Redraw:
    index: int
    attempt: int
    value: float
    reason: str

    def as_record(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "attempt": self.attempt,
            "value": self.value,
            "reason": self.reason,
        }


class RegimeDrawer:
    """Draws regime ``i`` for a seed, asking the gate about each candidate in turn."""

    def __init__(self, seed: int, cfg: SimConfig) -> None:
        self.seed = seed
        self.low, self.high = cfg["demand_total_factor_min_v2"], cfg["demand_regime_max"]
        self.dwell = (cfg["demand_regime_dwell_min_s"], cfg["demand_regime_dwell_max_s"])
        self.ramp_s = cfg["demand_regime_ramp_s"]
        self.max_draws = int(cfg["demand_regime_max_draws"])

    def draw(self, index: int, t_start: float, gate: Gate) -> tuple[Regime, list[Redraw]]:
        rng = RandomStreams(self.seed).stream(f"{REGIME_STREAM}/{index}")
        redraws: list[Redraw] = []
        for attempt in range(1, self.max_draws + 1):
            value = math.exp(rng.uniform(math.log(self.low), math.log(self.high)))
            dwell = float(rng.uniform(*self.dwell))
            reason = gate(value)
            if reason is None:
                ramp = 0.0 if index == 0 else self.ramp_s
                return Regime(index, t_start, value, dwell, ramp, attempt), redraws
            redraws.append(Redraw(index, attempt, value, reason))
        raise ContractError(
            f"demand regime {index}: no candidate passed the gates in {self.max_draws} draws"
        )


def regime_value(regimes: list[Regime], t: float) -> float:
    """Piecewise constant regime value with a linear ramp into each regime after the first."""
    for k in range(len(regimes) - 1, -1, -1):
        r = regimes[k]
        if t >= r.t_start_s:
            if k > 0 and t < r.plateau_start_s:
                a = (t - r.t_start_s) / r.ramp_s
                return regimes[k - 1].value + a * (r.value - regimes[k - 1].value)
            return r.value
    return regimes[0].value


class RegimeDemand:
    """The downstream factor of profile v2, with the interface of ``DemandProcess``."""

    def __init__(
        self,
        ou: DemandProcess,
        floor: float,
        regimes: Callable[[], list[Regime]],
        extend: Callable[[], None],
    ) -> None:
        self.ou, self.floor, self._regimes, self._extend = ou, floor, regimes, extend

    def _ensure(self, t: float) -> list[Regime]:
        if not self._regimes():
            self._extend()
        while t > self._regimes()[-1].plateau_end_s:
            self._extend()
        return self._regimes()

    def regime(self, t: float) -> float:
        return regime_value(self._ensure(t), t)

    def factor(self, t: float) -> float:
        return max(self.regime(t) * self.ou.factor(t), self.floor)

    def unclipped_log(self, t: float) -> float:
        return math.log(self.regime(t)) + self.ou.unclipped_log(t)


class SetpointDeviation:
    """Ornstein-Uhlenbeck deviation of the receipt set-point as a fraction, clipped."""

    def __init__(self, seed: int, duration_s: float, cfg: SimConfig) -> None:
        self.clip = cfg["receipt_setpoint_clip_fraction"]
        n = int(math.ceil(duration_s / GRID_S)) + 2
        # The OU path is the one of the demand process with other parameters and another stream.
        self.path = _ou_path(
            RandomStreams(seed).stream(RECEIPT_STREAM),
            n,
            cfg["receipt_setpoint_sigma_fraction"],
            cfg["receipt_setpoint_correlation_time_s"],
        )

    def fraction(self, t: float) -> float:
        s = max(t, 0.0) / GRID_S
        k = min(int(s), len(self.path) - 2)
        x = self.path[k] + (s - k) * (self.path[k + 1] - self.path[k])
        return float(min(max(x, -self.clip), self.clip))

    def effective(self, nominal_m3h: float, t: float) -> float:
        """The set-point the controller follows; zero stays zero."""
        return nominal_m3h * (1.0 + self.fraction(t)) if nominal_m3h > 0.0 else nominal_m3h


def _ou_path(rng: np.random.Generator, n: int, sigma: float, tau_s: float) -> np.ndarray:
    phi = math.exp(-GRID_S / tau_s)
    noise = rng.standard_normal(n)
    first = sigma * noise[0]
    rest, _ = lfilter(
        [sigma * math.sqrt(1.0 - phi * phi)], [1.0, -phi], noise[1:], zi=[phi * first]
    )
    return np.concatenate(([first], rest))


def check_receipt_headroom(setpoints_m3h: list[float], limit_m3h: float, clip: float) -> None:
    """Decision D73: the set-point at its largest clipped value must pass the headroom screen."""
    for sp in sorted(set(setpoints_m3h)):
        if sp * (1.0 + clip) > limit_m3h:
            raise ContractError(
                f"scenario: receipt set-point {sp:g} m3/h at {1.0 + clip:g} times is "
                f"{sp * (1.0 + clip):.1f} m3/h, above the headroom limit {limit_m3h:.1f} m3/h"
            )

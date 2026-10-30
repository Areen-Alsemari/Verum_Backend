"""Shared case builders and a reference-case variable-speed pump for the hydraulics tests.

The variable-speed pump exists only in tests and reproduces the audited required-head and
speed-ratio figures, while production code has only the fixed-speed pump. A switch turns the Q / s
<= 350 domain rule on or off, so the same pump can first be used to find a speed ratio and then to
show the rejection.

See D2.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from verum.graph import Lineup
from verum.hydraulics import DeliveryBoundary, ReceiptBoundary, SteadyInputs

SCENARIO = "EPA_GENERIC_RVP10_REFERENCE"
INITIAL_LEVELS = {"TK-101": 9.0, "TK-102": 7.0, "TK-103": 5.0}
TANKS = ("TK-101", "TK-102", "TK-103")


def deliver_lineup(tank: str, pump: str = "A") -> Lineup:
    n = tank[3:]
    return Lineup.of({f"XV-S{n}", f"XV-P{pump}I", f"XV-P{pump}O"}, {f"P-101{pump}"})


def receive_lineup(*tanks: str) -> Lineup:
    return Lineup.of({"XV-R000", *[f"XV-R{t[3:]}" for t in tanks]})


def delivery_case(
    tank: str,
    level: float,
    *,
    pump: str = "A",
    profile: str = "pipe_only",
    multiplier: float = 1.0,
    temperature_c: float = 25.0,
    law: float | None = None,
    pump_element: object = None,
    npsh3: float | None = None,
    reservoir_pa: float | None = None,
) -> SteadyInputs:
    return SteadyInputs(
        lineup=deliver_lineup(tank, pump),
        tank_levels_m={tank: level},
        scenario=SCENARIO,
        temperature_c=temperature_c,
        fitting_profile=profile,
        k_multiplier=multiplier,
        delivery=DeliveryBoundary(law_coefficient_m=law, reservoir_pressure_pa_gauge=reservoir_pa),
        pump=pump_element,  # type: ignore[arg-type]
        npsh3_coefficient_m=npsh3,
    )


def receipt_case(
    tanks: tuple[str, ...],
    levels: Mapping[str, float] = INITIAL_LEVELS,
    receipt: ReceiptBoundary | None = None,
    profile: str = "pipe_only",
) -> SteadyInputs:
    return SteadyInputs(
        lineup=receive_lineup(*tanks),
        tank_levels_m=dict(levels),
        scenario=SCENARIO,
        temperature_c=25.0,
        fitting_profile=profile,
        receipt=receipt or ReceiptBoundary(),
    )


@dataclass(frozen=True)
class VariableSpeedPump:
    """``H(Q, s) = 54 s^2 - 12 (Q / 300)^2``, valid for ``0 <= Q / s <= 350``."""

    speed_ratio: float
    enforce_domain: bool = True
    h0: float = 54.0
    k: float = 12.0
    q_ref: float = 300.0
    q_max: float = 350.0

    @property
    def shutoff_head_m(self) -> float:
        return self.h0 * self.speed_ratio**2

    def head_rise_m(self, flow_m3h: float) -> float:
        return self.shutoff_head_m - self.k * (flow_m3h / self.q_ref) ** 2

    def flow_m3s(self, delta_m: float) -> float:
        rise = -delta_m
        if rise >= self.shutoff_head_m:
            return 0.0
        return self.q_ref * math.sqrt((self.shutoff_head_m - rise) / self.k) / 3600.0

    def slope(self, delta_m: float) -> float:
        if -delta_m >= self.shutoff_head_m:
            return 0.0
        gap = max(self.shutoff_head_m + delta_m, 1e-9)
        return self.q_ref / 3600.0 * 0.5 / math.sqrt(self.k * gap)

    def in_domain(self, flow_m3h: float) -> bool:
        if not self.enforce_domain:
            return True
        return 0.0 <= flow_m3h / self.speed_ratio <= self.q_max

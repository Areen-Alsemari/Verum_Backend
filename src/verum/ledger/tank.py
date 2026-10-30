"""Per-tank inventory ledger driven by prescribed flows.

Two statements are kept apart. The liquid-only ledger subtracts the net evaporation into vapor,
while the total-product ledger subtracts only vapor that leaves the tank, because evaporation is an
internal transfer. Subtracting evaporation in both would remove it twice. A leak is a single sink.
The flows are inputs and nothing here computes a flow from pressure. Rounding is bounded by the
recursive-summation rule (n - 1) 2^-53 sum|x|, accumulated per run, so a residual is judged against
the arithmetic actually performed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from verum.tanks import TankGeometry

UNIT_ROUNDOFF: Final = 2.0**-53


class LedgerError(ValueError):
    """Raised for a step that is not physically admissible."""


def closure_tolerance(terms: list[float]) -> float:
    """Round-off bound ``(n - 1) 2^-53 sum|x|`` for summing ``terms`` recursively."""
    n = len(terms)
    if n < 2:
        return 0.0
    return (n - 1) * UNIT_ROUNDOFF * sum(abs(x) for x in terms)


@dataclass(frozen=True)
class TankFlows:
    """Prescribed masses (kg) over one step; all are non-negative."""

    mass_in_kg: float = 0.0
    mass_out_kg: float = 0.0
    leak_kg: float = 0.0
    evaporation_kg: float = 0.0
    vapor_out_kg: float = 0.0

    def __post_init__(self) -> None:
        for name, value in vars(self).items():
            if not value >= 0.0:
                raise LedgerError(f"{name} must be a non-negative finite number")


@dataclass
class _Totals:
    mass_in: float = 0.0
    mass_out: float = 0.0
    leak: float = 0.0
    evaporation: float = 0.0
    vapor_out: float = 0.0


@dataclass
class TankLedger:
    """Liquid and vapor inventory of one tank."""

    tank_id: str
    initial_liquid_kg: float
    initial_vapor_kg: float = 0.0
    liquid_kg: float = field(init=False)
    vapor_kg: float = field(init=False)
    totals: _Totals = field(default_factory=_Totals, init=False)
    terms: list[float] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        if self.initial_liquid_kg < 0 or self.initial_vapor_kg < 0:
            raise LedgerError("initial inventory must not be negative")
        self.liquid_kg = self.initial_liquid_kg
        self.vapor_kg = self.initial_vapor_kg
        # The initial inventory is the first term of every recursive sum below,
        # and the rounding error scales with the size of the running state.
        self.terms = [self.initial_liquid_kg, self.initial_vapor_kg]

    @property
    def total_kg(self) -> float:
        """Total product: liquid plus vapor."""
        return self.liquid_kg + self.vapor_kg

    def apply(self, flows: TankFlows) -> None:
        """Advance one step; reject a step that would make an inventory negative."""
        liquid = self.liquid_kg + flows.mass_in_kg - flows.mass_out_kg - flows.leak_kg
        liquid -= flows.evaporation_kg
        vapor = self.vapor_kg + flows.evaporation_kg - flows.vapor_out_kg
        if liquid < 0 or vapor < 0:
            raise LedgerError(f"{self.tank_id}: step would give a negative inventory")
        self.liquid_kg, self.vapor_kg = liquid, vapor
        t = self.totals
        t.mass_in += flows.mass_in_kg
        t.mass_out += flows.mass_out_kg
        t.leak += flows.leak_kg
        t.evaporation += flows.evaporation_kg
        t.vapor_out += flows.vapor_out_kg
        self.terms += [
            flows.mass_in_kg,
            -flows.mass_out_kg,
            -flows.leak_kg,
            -flows.evaporation_kg,
            flows.evaporation_kg,
            -flows.vapor_out_kg,
        ]

    def liquid_residual_kg(self) -> float:
        """Change in liquid mass minus (in - out - leak - evaporation): E5."""
        t = self.totals
        return (self.liquid_kg - self.initial_liquid_kg) - (
            t.mass_in - t.mass_out - t.leak - t.evaporation
        )

    def total_residual_kg(self) -> float:
        """Change in total product minus (in - out - leak - vapor out): E5T."""
        t = self.totals
        initial = self.initial_liquid_kg + self.initial_vapor_kg
        return (self.total_kg - initial) - (t.mass_in - t.mass_out - t.leak - t.vapor_out)

    def error_terms(self) -> list[float]:
        """Every term summed so far, including the final state that is differenced."""
        return [*self.terms, -self.liquid_kg, -self.vapor_kg]

    def tolerance_kg(self) -> float:
        """Round-off bound for this tank's run so far."""
        return closure_tolerance(self.error_terms())

    def volume_m3(self, rho: float) -> float:
        return self.liquid_kg / rho

    def level_m(self, geometry: TankGeometry, rho: float) -> float:
        return geometry.level_m(self.volume_m3(rho), rho)

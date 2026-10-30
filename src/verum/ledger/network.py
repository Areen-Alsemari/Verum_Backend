"""Network inventory ledger over the tanks, driven by prescribed flows.

Each step takes the mass received, the mass delivered, the flows of each tank and the mass lost
through pipe leaks, and gives two network residuals (liquid only and total product) with their
round-off tolerances. The pipes stay full and their stored mass is constant, so line-pack change is
zero by construction and the closure says nothing about transient storage. A leak is one sink,
subtracted from the network once. The tolerance is the recursive-summation bound over every term
used in the run.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from verum.ledger.tank import LedgerError, TankFlows, TankLedger, closure_tolerance
from verum.tanks import TankGeometry


@dataclass(frozen=True)
class Closure:
    """A residual with the round-off tolerance of the run that produced it."""

    residual_kg: float
    tolerance_kg: float

    @property
    def closed(self) -> bool:
        return abs(self.residual_kg) <= self.tolerance_kg


@dataclass
class NetworkLedger:
    """Ledger over all tanks plus the two external boundaries."""

    tanks: dict[str, TankLedger]
    received_kg: float = field(default=0.0, init=False)
    delivered_kg: float = field(default=0.0, init=False)
    pipe_spill_kg: float = field(default=0.0, init=False)
    terms: list[float] = field(default_factory=list, init=False)

    def step(
        self,
        received_kg: float,
        delivered_kg: float,
        tank_flows: Mapping[str, TankFlows],
        pipe_spill_kg: float = 0.0,
    ) -> None:
        """Advance one step with prescribed masses (kg)."""
        for value in (received_kg, delivered_kg, pipe_spill_kg):
            if not value >= 0.0:
                raise LedgerError("boundary and spill masses must be non-negative")
        unknown = set(tank_flows) - set(self.tanks)
        if unknown:
            raise LedgerError(f"unknown tanks {sorted(unknown)}")
        for tank_id, flows in tank_flows.items():
            self.tanks[tank_id].apply(flows)
        self.received_kg += received_kg
        self.delivered_kg += delivered_kg
        self.pipe_spill_kg += pipe_spill_kg
        self.terms += [received_kg, -delivered_kg, -pipe_spill_kg]

    @property
    def spill_kg(self) -> float:
        """Total mass that left through leaks: pipes and tanks, counted once."""
        return self.pipe_spill_kg + sum(t.totals.leak for t in self.tanks.values())

    def liquid_closure(self) -> Closure:
        """received - delivered - spill - evaporation - change of liquid inventory."""
        evaporation = sum(t.totals.evaporation for t in self.tanks.values())
        change = sum(t.liquid_kg - t.initial_liquid_kg for t in self.tanks.values())
        residual = self.received_kg - self.delivered_kg - self.spill_kg - evaporation - change
        return Closure(residual, self._tolerance(change, evaporation))

    def total_closure(self) -> Closure:
        """received - delivered - spill - vapor out - change of total inventory."""
        vapor_out = sum(t.totals.vapor_out for t in self.tanks.values())
        change = sum(
            t.total_kg - (t.initial_liquid_kg + t.initial_vapor_kg) for t in self.tanks.values()
        )
        residual = self.received_kg - self.delivered_kg - self.spill_kg - vapor_out - change
        return Closure(residual, self._tolerance(change, vapor_out))

    def _tolerance(self, change: float, sink: float) -> float:
        terms = list(self.terms)
        for tank in self.tanks.values():
            terms += tank.error_terms()
        terms += [change, -sink, -self.spill_kg]
        return closure_tolerance(terms)

    def levels_m(self, geometry: TankGeometry, rho: float) -> dict[str, float]:
        """Level of every tank from its liquid inventory."""
        return {k: t.level_m(geometry, rho) for k, t in self.tanks.items()}

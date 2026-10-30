"""Boundary specifications and the over-constraint check (gate G2).

The receipt boundary has one degree of freedom: either the total flow is imposed and the source
pressure is solved, or the pressure is imposed and the flow is solved. Imposing both is rejected,
and imposing neither takes the configured flow. The delivery boundary imposes the reservoir pressure
and the boundary law, so the pump and network fix the flow and a delivery flow cannot be imposed as
well. A boundary-law coefficient of exactly zero makes the boundary a fixed-pressure node.

See D2 and D3.
"""

from __future__ import annotations

from dataclasses import dataclass

from verum.hydraulics.errors import OverConstrained


@dataclass(frozen=True)
class ReceiptBoundary:
    """Receipt source: total flow (m3/h) or source pressure (Pa gauge), not both."""

    flow_m3h: float | None = None
    pressure_pa_gauge: float | None = None

    def validate(self) -> None:
        if self.flow_m3h is not None and self.pressure_pa_gauge is not None:
            raise OverConstrained("receipt: flow and source pressure are both imposed")
        for value in (self.flow_m3h, self.pressure_pa_gauge):
            if value is not None and value < 0:
                raise ValueError("receipt boundary values must not be negative")


@dataclass(frozen=True)
class DeliveryBoundary:
    """Delivery: reservoir pressure and law coefficient; a flow cannot be imposed."""

    reservoir_pressure_pa_gauge: float | None = None
    law_coefficient_m: float | None = None
    flow_m3h: float | None = None

    def validate(self) -> None:
        if self.flow_m3h is not None:
            raise OverConstrained(
                "delivery: the reservoir pressure is imposed and the pump is fixed, "
                "so a delivery flow cannot also be imposed"
            )
        if self.law_coefficient_m is not None and self.law_coefficient_m < 0:
            raise ValueError("the boundary-law coefficient must not be negative")

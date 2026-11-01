"""One-sided roof hang-up geometry and its buoyancy/support balance.

A rigid deck starts floating and is then held at that elevation while the liquid withdraws.
The model uses the existing displacement geometry and computes the support reaction from weight
minus buoyancy. Rising liquid and structural rupture are outside this model's qualified domain.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from verum.params import ParamValue
from verum.tanks.geometry import TankGeometry


@dataclass(frozen=True)
class RoofHangup:
    base_geometry: TankGeometry
    anchor_level_m: float
    density_kg_m3: float
    gravity_m_s2: float

    def __post_init__(self) -> None:
        if not all(math.isfinite(v) for v in (
            self.anchor_level_m, self.density_kg_m3, self.gravity_m_s2
        )):
            raise ValueError("roof inputs must be finite")
        if self.density_kg_m3 <= 0 or self.gravity_m_s2 <= 0:
            raise ValueError("density and gravity must be positive")
        if self.anchor_level_m < self.base_geometry.floating_level_m(self.density_kg_m3):
            raise ValueError("the initial roof must be floating above its normal supports")

    @property
    def calibration(self) -> TankGeometry:
        """Volume calibration with the roof underside held at its initial floating elevation."""
        bottom = self.anchor_level_m - self.base_geometry.draft_m(self.density_kg_m3)
        return replace(self.base_geometry, support_height_m=bottom)

    @property
    def weight_n(self) -> float:
        return self.base_geometry.deck_mass_kg() * self.gravity_m_s2

    def support_reaction_n(self, level_m: float) -> float:
        """Upward support reaction in N; no material strength or rupture threshold is assumed."""
        if not math.isfinite(level_m) or not 0 <= level_m <= self.anchor_level_m:
            raise ValueError("support reaction is defined only for withdrawal below the anchor")
        geometry = self.calibration
        immersion = min(max(level_m - geometry.support_height_m, 0.),
                        geometry.draft_m(self.density_kg_m3))
        buoyancy = self.density_kg_m3 * self.gravity_m_s2 * geometry.deck_area_m2 * immersion
        return max(0., self.weight_n - buoyancy)

    def capacity_margin_n(self, level_m: float, capacity: ParamValue) -> float:
        """Capacity minus support reaction in N; an unspecified capacity remains unresolved."""
        if capacity.unit != "N" or capacity.value <= 0:
            raise ValueError("a referenced positive support capacity in N is required")
        return capacity.value - self.support_reaction_n(level_m)

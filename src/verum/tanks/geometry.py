"""Tank volume, inverse level and roof state for an internal floating roof.

The tank has a flat bottom and a uniform contacting deck, and density is constant per evaluation.
The volume is the net liquid volume, not the cylinder volume. The deck rests at height z_s. Above it
the deck displaces liquid in proportion to the immersion, up to the draft d = m_areal / rho, and
beyond that it floats and the displacement is constant. The roof is landed at or below z_s, floating
at or above z_s + d, and in transition between. Shell height and level limits are applied elsewhere.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from verum.contracts.errors import ContractError
from verum.contracts.paths import config_dir
from verum.params import ParamValue, ParamValueError

FILENAME: Final = "tank_geometry.json"
_REQUIRED: Final = (
    "shell_diameter_m",
    "deck_diameter_m",
    "roof_support_height_m",
    "roof_areal_mass_kg_m2",
)


@dataclass(frozen=True)
class TankGeometry:
    """Areas in m2, heights in m, areal mass in kg/m2."""

    area_m2: float
    deck_area_m2: float
    support_height_m: float
    areal_mass_kg_m2: float

    def __post_init__(self) -> None:
        if not 0 < self.deck_area_m2 < self.area_m2:
            raise ValueError("deck area must be positive and smaller than the tank area")
        if self.support_height_m < 0 or self.areal_mass_kg_m2 < 0:
            raise ValueError("support height and areal mass must not be negative")

    @classmethod
    def from_params(
        cls,
        shell_diameter: ParamValue,
        deck_diameter: ParamValue,
        support_height: ParamValue,
        areal_mass: ParamValue,
    ) -> TankGeometry:
        """Build from parameter records; an unresolved record raises on access."""
        return cls(
            area_m2=math.pi * shell_diameter.value**2 / 4,
            deck_area_m2=math.pi * deck_diameter.value**2 / 4,
            support_height_m=support_height.value,
            areal_mass_kg_m2=areal_mass.value,
        )

    def draft_m(self, rho: float) -> float:
        """Immersion depth of the floating deck."""
        _check_density(rho)
        return self.areal_mass_kg_m2 / rho

    def displacement_m3(self, rho: float) -> float:
        """Liquid volume displaced by the floating deck."""
        return self.deck_area_m2 * self.draft_m(rho)

    def deck_mass_kg(self) -> float:
        return self.areal_mass_kg_m2 * self.deck_area_m2

    def lift_off_level_m(self) -> float:
        """Level at which the deck starts to displace liquid."""
        return self.support_height_m

    def floating_level_m(self, rho: float) -> float:
        """Level from which the deck floats freely."""
        return self.support_height_m + self.draft_m(rho)

    def volume_m3(self, level_m: float, rho: float) -> float:
        """Net liquid volume at a level."""
        if level_m < 0:
            raise ValueError("level must not be negative")
        immersion = min(max(level_m - self.support_height_m, 0.0), self.draft_m(rho))
        return self.area_m2 * level_m - self.deck_area_m2 * immersion

    def level_m(self, volume_m3: float, rho: float) -> float:
        """Level for a net liquid volume, on the branch that contains it."""
        if volume_m3 < 0:
            raise ValueError("volume must not be negative")
        v_landed = self.area_m2 * self.support_height_m
        v_floating = self.volume_m3(self.floating_level_m(rho), rho)
        if volume_m3 <= v_landed:
            return volume_m3 / self.area_m2
        if volume_m3 < v_floating:
            numerator = volume_m3 - self.deck_area_m2 * self.support_height_m
            return numerator / (self.area_m2 - self.deck_area_m2)
        return (volume_m3 + self.displacement_m3(rho)) / self.area_m2

    def roof_state(self, level_m: float, rho: float) -> str:
        """``landed``, ``transition`` or ``floating``."""
        if level_m <= self.support_height_m:
            return "landed"
        if level_m < self.floating_level_m(rho):
            return "transition"
        return "floating"

    def level_rise_m(self, net_volume_m3: float) -> float:
        """Level change for a net volume added on the floating branch (E6)."""
        return net_volume_m3 / self.area_m2


def _check_density(rho: float) -> None:
    if not math.isfinite(rho) or rho <= 0:
        raise ValueError("density must be positive and finite")


def load_tank_parameters(directory: Path | None = None) -> dict[str, ParamValue]:
    """Load every parameter record of the tank geometry configuration."""
    path = (directory or config_dir()) / FILENAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))["parameters"]
        return {name: ParamValue.from_mapping(record) for name, record in raw.items()}
    except (OSError, json.JSONDecodeError, KeyError, ParamValueError) as exc:
        raise ContractError(f"cannot read {path}: {exc!r}") from exc


def load_tank_geometry(directory: Path | None = None) -> TankGeometry:
    """Build the tank geometry from configuration."""
    parameters = load_tank_parameters(directory)
    missing = [name for name in _REQUIRED if name not in parameters]
    if missing:
        raise ContractError(f"tank geometry: missing parameters {missing}")
    return TankGeometry.from_params(*(parameters[name] for name in _REQUIRED))

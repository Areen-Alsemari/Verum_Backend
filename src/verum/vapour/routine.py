"""Source-matched routine IFRT loss components with explicit construction inputs.

The June 2026 AP-42 method applies to maintained equipment and monthly-or-longer windows.
Construction comparisons are not damaged-material predictions or continuous VOC observations.
Unmatched penetrations and unspecified seams remain unresolved rather than receiving proxies.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from verum.contracts.paths import config_dir
from verum.params import ParamValue, UnresolvedParameter
from verum.vapour.model import FT_M, LB_KG, pressure_function

BARREL_M3 = 0.158987294928  # 42 US gallons, exact unit conversion
INCH_M = 0.0254


class RoutineFactors:
    def __init__(self, path: Path | None = None) -> None:
        raw = (path or config_dir() / "extensions" / "ap42_routine_v1.json").read_bytes()
        self.hash = hashlib.sha256(raw).hexdigest()
        self.parameters = {k: ParamValue.from_mapping(v)
                           for k, v in json.loads(raw)["parameters"].items()}

    def value(self, key: str) -> float:
        if key not in self.parameters:
            raise UnresolvedParameter(f"no source-matched routine factor for {key}")
        return self.parameters[key].value


def _value(record: ParamValue, unit: str, *, positive: bool = False) -> float:
    if record.unit != unit:
        raise ValueError(f"expected {unit}, received {record.unit}")
    value = record.value
    if not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError("physical input lies outside its nonnegative domain")
    return value


def uncontrolled_fitting_factor(
    exposed_area: ParamValue, well_height: ParamValue, factors: RoutineFactors,
    *, uncontrolled: bool,
) -> float:
    """Equation 2-17 in lbmol/yr, only for uncontrolled wells at least 12 inches high."""
    if not uncontrolled:
        raise ValueError("equation 2-17 does not quantify fitting controls")
    area = _value(exposed_area, "m2", positive=True)
    height = _value(well_height, "m", positive=True)
    if height < factors.value("uncontrolled_min_well_height"):
        raise UnresolvedParameter("AP-42 supplies no correlation for shorter wells")
    return float(factors.value("uncontrolled_area_coefficient") * (
        area / INCH_M**2
    ) ** factors.value("uncontrolled_area_exponent"))


def cumulative_fall(levels: list[tuple[float, float]]) -> float:
    """Sum decreases in recorded liquid level in m; simultaneous gross discharge is not used."""
    if len(levels) < 2 or any(isinstance(v, bool) or not math.isfinite(v) or v < 0
                              for row in levels for v in row):
        raise ValueError("at least two finite nonnegative time/level samples are required")
    if any(b[0] <= a[0] for a, b in zip(levels, levels[1:], strict=False)):
        raise ValueError("level samples must increase strictly in time")
    return sum(max(a[1] - b[1], 0.) for a, b in zip(levels, levels[1:], strict=False))


def withdrawal_kg(
    level_fall: ParamValue, diameter: ParamValue, density: ParamValue,
    column_perimeter: ParamValue, shell_condition: str, factors: RoutineFactors,
) -> float:
    """Withdrawal clingage in kg from wetted wall/column area, equivalent to AP-42 2-19/2-20."""
    drop = _value(level_fall, "m")
    circumference = math.pi * _value(diameter, "m", positive=True)
    perimeter = _value(column_perimeter, "m")
    rho = _value(density, "kg/m3", positive=True)
    # Shell condition must be selected explicitly; a generic steel tank does not select it.
    film = factors.value("gasoline_" + shell_condition) * BARREL_M3 / (1000 * FT_M**2)
    return (circumference + perimeter) * drop * film * rho


def seam_factor(
    construction: str, seam_length: ParamValue, deck_area: ParamValue,
    diameter: ParamValue, factors: RoutineFactors,
) -> float:
    """Equation 2-18 equivalent coefficient in lbmol/yr, before P*, molecular weight and Kc."""
    if construction not in ("welded", "bolted"):
        raise UnresolvedParameter("honeycomb/full contact does not specify seam construction")
    if construction == "welded":
        return 0.  # EPA's stated applicability, not an assumed honeycomb classification
    length_ft = _value(seam_length, "m") / FT_M
    area_ft2 = _value(deck_area, "m2", positive=True) / FT_M**2
    diameter_ft = _value(diameter, "m", positive=True) / FT_M
    return factors.value("bolted_seam_factor") * length_ft / area_ft2 * diameter_ft**2


def standing_components_kg(
    pressure_pa_abs: ParamValue, atmosphere_pa_abs: ParamValue, molecular_mass: ParamValue,
    year_fraction: ParamValue, diameter: ParamValue, rim_factor: ParamValue,
    fittings: list[tuple[ParamValue, str]], deck_coefficient: ParamValue,
    factors: RoutineFactors, *, maintained: bool, freely_vented: bool, continuously_floating: bool,
    extra_fitting_coefficient: ParamValue | None = None,
) -> dict[str, Any]:
    """Normal gasoline rim/fitting/seam terms, with explicit inventory classifications."""
    if not (maintained and freely_vented and continuously_floating):
        raise ValueError("routine factors exclude damaged, unvented or landed operation")
    fraction = _value(year_fraction, "1", positive=True)
    if fraction * factors.value("reference_year_days") < factors.value("minimum_estimation_days"):
        raise ValueError("routine estimation retains the declared minimum 30-day window")
    pstar = pressure_function(_value(pressure_pa_abs, "Pa_abs"),
                              _value(atmosphere_pa_abs, "Pa_abs", positive=True))
    scale = (pstar * _value(molecular_mass, "kg/kmol", positive=True) * LB_KG * fraction *
             factors.value("product_factor"))
    ff = (0. if extra_fitting_coefficient is None else
          _value(extra_fitting_coefficient, "lbmol/yr"))
    for count, construction in fittings:
        n = _value(count, "1")
        if not n.is_integer():
            raise ValueError("fitting inventory counts must be integers")
        # Zero is an explicit absence; it does not impute a coefficient to an existing opening.
        if n:
            factors.value(construction)  # unknown keys remain explicitly unresolved
            ff += n * _value(factors.parameters[construction], "lbmol/yr")
    rim = (_value(rim_factor, "lbmol/(ft yr)") *
           _value(diameter, "m", positive=True) / FT_M * scale)
    fitting = ff * scale
    seam = _value(deck_coefficient, "lbmol/yr") * scale
    return {"rim_kg": rim, "fitting_kg": fitting, "seam_kg": seam,
            "standing_components_kg": rim + fitting + seam, "is_observation": False,
            "method": "AP42_2026_IFRT_normal_components", "factor_hash": factors.hash,
            "uncertainty": {"status": "unresolved", "reason": "no facility-specific error model"},
            "facility_qualified": False, "inventory_completeness": "caller_declared",
            "limits": ["constant_conditions", "no_damage_prediction", "withdrawal_separate",
                       "not_a_complete_window_without_throughput_and_duration_review"]}

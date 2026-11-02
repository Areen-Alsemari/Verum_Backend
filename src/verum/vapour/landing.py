"""EPA liquid-heel landing components for normally supported internal floating roofs.

The caller supplies the actual heel, vapour conditions and daily expansion factor.
The method accounts separately for idle breathing and refilling, including a change of service.
It predicts neither pressure under a jammed roof nor damaged-material emissions or VOC readings.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from verum.contracts.paths import config_dir
from verum.params import ParamValue, UnresolvedParameter
from verum.vapour.model import FT_M, LB_KG
from verum.vapour.routine import _value

PSI_PA = 6894.757293168


class LandingFactors:
    def __init__(self, path: Path | None = None) -> None:
        raw = (path or config_dir() / "extensions" / "ap42_landing_v1.json").read_bytes()
        self.hash = hashlib.sha256(raw).hexdigest()
        self.parameters = {
            k: ParamValue.from_mapping(v) for k, v in json.loads(raw)["parameters"].items()
        }

    def value(self, key: str) -> float:
        return self.parameters[key].value


def landing_daily_expansion(
    mean_temperature: ParamValue,
    temperature_span: ParamValue,
    pressure: ParamValue,
    pressure_span: ParamValue,
    atmosphere: ParamValue,
) -> ParamValue:
    """Equation 1-5 for a normal landing, with the source's zero vent-setting range."""
    mean = _value(mean_temperature, "K", positive=True)
    delta_t = _value(temperature_span, "K")
    pv = _value(pressure, "Pa_abs")
    pa = _value(atmosphere, "Pa_abs", positive=True)
    delta_p = _value(pressure_span, "Pa")
    if pv >= pa:
        raise ValueError("stock vapour pressure must be below atmospheric pressure")
    value = min(1.0, delta_t / mean + delta_p / (pa - pv))
    return ParamValue.selected(value, "1/day", "CALC", "EPA-2026-equation-1-5-landing-deltaPB-zero")


def saturated_mass_kg(
    pressure: ParamValue,
    atmosphere: ParamValue,
    temperature: ParamValue,
    molecular_mass: ParamValue,
    volume: ParamValue,
    factors: LandingFactors,
) -> float:
    """Ideal-gas saturated stock vapour mass in kg with EPA's customary-unit gas constant."""
    pv = _value(pressure, "Pa_abs")
    if pv >= _value(atmosphere, "Pa_abs", positive=True):
        raise ValueError("stock vapour pressure must be below atmospheric pressure")
    temp = _value(temperature, "K", positive=True)
    mw = _value(molecular_mass, "kg/kmol", positive=True)
    vv = _value(volume, "m3")
    return pv / PSI_PA * vv / FT_M**3 / (factors.value("gas_constant") * temp * 1.8) * mw * LB_KG


def heel_landing_episode(
    *,
    diameter: ParamValue,
    vapour_height: ParamValue,
    heel_volume: ParamValue,
    liquid_density: ParamValue,
    idle_time: ParamValue,
    daily_expansion: ParamValue,
    prior_pressure: ParamValue,
    atmosphere: ParamValue,
    prior_temperature: ParamValue,
    prior_molecular_mass: ParamValue,
    heel: str,
    normal_supported_landing: bool,
    freely_vented: bool,
    maintained: bool,
    refill_completed: bool,
    incoming_pressure: ParamValue | None = None,
    incoming_temperature: ParamValue | None = None,
    incoming_molecular_mass: ParamValue | None = None,
    factors: LandingFactors | None = None,
) -> dict[str, Any]:
    """Equations 3-7/16/18 and Table 7.1-17, capped by available liquid-heel mass.

    Expansion is explicitly supplied in 1/day; no weather, pressure or vent response is invented.
    """
    if any(v is not True for v in (normal_supported_landing, freely_vented, maintained)):
        raise ValueError("normal landing equations do not describe damaged or blocked-vent roofs")
    if not isinstance(refill_completed, bool):
        raise ValueError("refilling status must be an explicit boolean")
    if heel not in ("full", "partial"):
        raise UnresolvedParameter("liquid-heel method requires an explicit full or partial heel")
    f = factors or LandingFactors()
    diameter_m = _value(diameter, "m", positive=True)
    height_m = _value(vapour_height, "m", positive=True)
    heel_m3 = _value(heel_volume, "m3", positive=True)
    available_kg = heel_m3 * _value(liquid_density, "kg/m3", positive=True)
    days = _value(idle_time, "s") / 86400.0
    expansion = _value(daily_expansion, "1/day")
    if expansion > 1:
        raise ValueError("a daily expansion factor cannot expel more than the vapour space")
    volume = ParamValue.selected(
        math.pi * diameter_m**2 / 4 * height_m,
        "m3",
        "CALC",
        "EPA-2026-equation-3-22-explicit-geometry",
    )
    saturated = saturated_mass_kg(
        prior_pressure, atmosphere, prior_temperature, prior_molecular_mass, volume, f
    )
    saturation = f.value(heel + "_heel_filling_saturation")
    ks = min(
        saturation,
        1
        / (
            1
            + f.value("idle_saturation_coefficient")
            * prior_pressure.value
            / PSI_PA
            * height_m
            / FT_M
        ),
    )
    uncapped_idle = days * expansion * saturated * ks
    idle = min(uncapped_idle, available_kg)
    arrival: float | None = None
    generated: float | None = None
    if refill_completed:
        if any(
            p is None for p in (incoming_pressure, incoming_temperature, incoming_molecular_mass)
        ):
            raise UnresolvedParameter("refilling needs explicit incoming-liquid vapour properties")
        assert incoming_pressure is not None and incoming_temperature is not None
        assert incoming_molecular_mass is not None
        incoming = saturated_mass_kg(
            incoming_pressure, atmosphere, incoming_temperature, incoming_molecular_mass, volume, f
        )
        generated = f.value("generated_saturation") * incoming
        arrival = min(
            (saturation - f.value("generated_saturation")) * saturated, available_kg - idle
        )
    filling = None if arrival is None or generated is None else arrival + generated
    return {
        "method": "AP42_2026_IFRT_liquid_heel_landing",
        "factor_hash": f.hash,
        "standing_idle_kg": idle,
        "uncapped_standing_idle_kg": uncapped_idle,
        "arrival_kg": arrival,
        "generated_kg": generated,
        "filling_kg": filling,
        "total_kg": None if filling is None else idle + filling,
        "available_prior_liquid_kg": available_kg,
        "vapour_volume_m3": volume.value,
        "idle_saturation": ks,
        "refill_completed": refill_completed,
        "is_observation": False,
        "facility_qualified": False,
        "uncertainty": {"status": "unresolved", "reason": "no equipment-specific error model"},
        "limits": [
            "normal_supported_IFRT_liquid_heel",
            "prescribed_constant_conditions",
            "daily_expansion_supplied",
            "no_vent_dynamics",
            "not_a_liquid_inventory_sink",
            "not_a_damage_model",
            "routine_losses_must_exclude_landed_period",
        ],
    }

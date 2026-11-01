"""Reduced roof mechanics, persistent damage and windowed vapour reference components.

The mechanical track uses stored liquid levels without feeding forces back into hydraulics.
A roof hang-up may tear a seal after an explicit relative-travel threshold, a synthetic failure
rule rather than a claim about field failure rates. Estimated vapour mass is separate bookkeeping.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verum.contracts.paths import config_dir
from verum.params import ParamValue, UnresolvedParameter
from verum.tanks import load_tank_geometry

TANKS = ("TK-101", "TK-102", "TK-103")
KINDS = ("RIM_SEAL_DETERIORATION", "FITTING_DAMAGE", "ROOF_LANDING_ABNORMAL")
FITTINGS = {"access_hatch": 1, "gauge_well": 1, "vacuum_breaker": 2, "suspension": 6}
SECONDS_DAY = 86400.0
LB_KG = 0.45359237
FT_M = 0.3048


class Parameters:
    def __init__(self, path: Path | None = None) -> None:
        raw = (path or config_dir() / "extensions" / "vapour_v1.json").read_bytes()
        self.hash = hashlib.sha256(raw).hexdigest()
        self.raw: dict[str, Any] = json.loads(raw)
        self.values = {k: ParamValue.from_mapping(v)
                       for k, v in self.raw["parameters"].items()}

    def __getitem__(self, name: str) -> float:
        return self.values[name].value


@dataclass(frozen=True)
class MechanicalFault:
    instance_id: str
    fault_type: str
    tank_id: str
    onset_s: float
    ramp_s: float
    peak: float
    fitting: str | None = None
    parent_id: str | None = None

    def __post_init__(self) -> None:
        if not self.instance_id or self.fault_type not in KINDS or self.tank_id not in TANKS:
            raise ValueError("unknown mechanical fault or tank")
        if not all(not isinstance(x, bool) and math.isfinite(x)
                   for x in (self.onset_s, self.ramp_s, self.peak)):
            raise ValueError("fault values must be finite")
        if self.onset_s < 0 or self.ramp_s <= 0 or not 0 < self.peak <= 1:
            raise ValueError("invalid onset, ramp or peak")
        if self.fault_type == "FITTING_DAMAGE":
            if self.fitting not in FITTINGS:
                raise ValueError("fitting must exist in the roof inventory")
        elif self.fitting is not None:
            raise ValueError("only fitting damage names a fitting")

    def severity(self, t: float) -> float:
        """Persistent ramp severity; damage cannot recover without a repair event."""
        if not math.isfinite(t) or t < 0:
            raise ValueError("time must be finite and nonnegative")
        return self.peak * min(1.0, max(0.0, (t - self.onset_s) / self.ramp_s))


def validate_graph(faults: list[MechanicalFault]) -> None:
    """Reject missing, cyclic, cross-tank or nonmechanistic cascade links."""
    by_id = {f.instance_id: f for f in faults}
    if len(by_id) != len(faults):
        raise ValueError("fault instance identifiers must be unique")
    for fault in faults:
        if fault.parent_id is None:
            continue
        parent = by_id.get(fault.parent_id)
        if parent is None or parent.onset_s >= fault.onset_s or parent.tank_id != fault.tank_id:
            raise ValueError("cascade parent must precede the child on the same tank")
        if (parent.fault_type, fault.fault_type) != (
            "ROOF_LANDING_ABNORMAL", "RIM_SEAL_DETERIORATION"
        ):
            raise ValueError("only roof hang-up to seal tear has a defined failure rule")


def cascade_child(
    parent: MechanicalFault, levels: list[tuple[float, float]], parameters: Parameters,
    *, allow_legacy_simulation: bool = False,
) -> MechanicalFault | None:
    """First sampled travel-threshold crossing after a fully established roof hang-up."""
    if not allow_legacy_simulation:
        raise UnresolvedParameter("no sourced quantitative roof-to-seal failure law; "
                                  "the legacy travel rule is restricted research only")
    if parent.fault_type != "ROOF_LANDING_ABNORMAL":
        raise ValueError("cascade requires a roof hang-up")
    if any(not math.isfinite(t) or not math.isfinite(level) or t < 0 or level < 0
           for t, level in levels):
        raise ValueError("level samples must be finite and nonnegative")
    if any(b[0] <= a[0] for a, b in zip(levels, levels[1:], strict=False)):
        raise ValueError("level sample times must increase strictly")
    established = parent.onset_s + parent.ramp_s
    samples = [(t, level) for t, level in levels if t >= established]
    if not samples:
        return None
    anchor = samples[0][1]
    for t, level in samples[1:]:
        if abs(level - anchor) >= parameters["seal_tear_displacement_m"]:
            return MechanicalFault(
                parent.instance_id + "-SEAL", "RIM_SEAL_DETERIORATION", parent.tank_id,
                t, parameters["seal_damage_ramp_s"], parent.peak, parent_id=parent.instance_id,
            )
    return None


def mechanical_state(
    faults: list[MechanicalFault], t: float, parameters: Parameters
) -> dict[str, dict[str, Any]]:
    """Mechanical inspection quantities for all tanks, with no change to liquid mass."""
    validate_graph(faults)
    if not math.isfinite(t) or t < 0:
        raise ValueError("time must be finite and nonnegative")
    result = {tank: {"rim_gap_m": 0.0, "fitting_damage": 0.0, "roof_hang_up": 0.0}
              for tank in TANKS}
    for fault in faults:
        severity = fault.severity(t)
        state = result[fault.tank_id]
        if fault.fault_type == "RIM_SEAL_DETERIORATION":
            state["rim_gap_m"] = max(state["rim_gap_m"],
                                     severity * parameters["rim_gap_at_full_damage_m"])
        elif fault.fault_type == "FITTING_DAMAGE":
            state["fitting_damage"] = max(state["fitting_damage"], severity)
        else:
            state["roof_hang_up"] = max(state["roof_hang_up"], severity)
    return result


def pressure_function(vapour_pa_abs: float, atmosphere_pa_abs: float) -> float:
    """AP-42 pressure function for absolute pressures, restricted to a ratio below one."""
    if not (math.isfinite(vapour_pa_abs) and math.isfinite(atmosphere_pa_abs)):
        raise ValueError("pressures must be finite")
    if atmosphere_pa_abs <= 0 or not 0 <= vapour_pa_abs < atmosphere_pa_abs:
        raise ValueError("vapour pressure must be below positive atmospheric pressure")
    ratio = vapour_pa_abs / atmosphere_pa_abs
    return ratio / (1.0 + math.sqrt(1.0 - ratio)) ** 2


def reference_window(
    temperature_k: float, diameter_m: float, days: float, seal_severity: float,
    fitting_severity: float, parameters: Parameters,
    fitting_kind: str | None = None,
    *, allow_legacy_simulation: bool = False,
) -> dict[str, Any]:
    """Synthetic constant-condition window components in kg; not a complete AP-42 tank total."""
    if not allow_legacy_simulation:
        raise UnresolvedParameter("legacy SIM proxies require explicit research opt-in; "
                                  "use source-matched routine components for normal equipment")
    if not all(math.isfinite(x) for x in (
        temperature_k, diameter_m, days, seal_severity, fitting_severity
    )):
        raise ValueError("window inputs must be finite")
    if not 288.15 <= temperature_k <= 318.15 or diameter_m <= 0:
        raise ValueError("window lies outside the reference temperature or diameter domain")
    if days < parameters["minimum_estimation_days"]:
        raise ValueError("routine reference windows must span at least 30 days")
    if not 0 <= seal_severity <= 1 or not 0 <= fitting_severity <= 1:
        raise ValueError("damage severity must lie in [0, 1]")
    pv = 6894.757293 * math.exp(parameters["vapour_pressure_a"] -
                              parameters["vapour_pressure_b_rankine"] / (1.8 * temperature_k))
    pstar = pressure_function(pv, parameters["atmosphere_pa_abs"])
    # A lb-mole of a substance with molar mass M has M pounds of mass.
    factor = pstar * parameters["vapour_molecular_mass"] * LB_KG
    factor *= days / parameters["reference_year_days"]
    damage_range = parameters["damage_multiplier_max"] - 1.0
    rim = parameters["rim_factor"] * diameter_m / FT_M * factor
    rim *= 1 + damage_range * seal_severity
    matched = (parameters["hatch_factor"] + parameters["gauge_factor"] +
               FITTINGS["vacuum_breaker"] * parameters["vacuum_factor"])
    proxy = FITTINGS["suspension"] * parameters["suspension_factor"]
    affected = {"access_hatch": parameters["hatch_factor"],
                "gauge_well": parameters["gauge_factor"],
                "vacuum_breaker": parameters["vacuum_factor"],
                "suspension": parameters["suspension_factor"]}
    if (fitting_severity > 0 or fitting_kind is not None) and fitting_kind not in affected:
        raise ValueError("damaged fitting must be named and present")
    extra = affected[fitting_kind] * fitting_severity * damage_range if fitting_kind else 0.0
    fittings = (matched + proxy + extra) * factor
    seam = parameters["seam_factor"] * factor
    return {
        "method": "synthetic_reference_components", "is_observation": False,
        "uncertainty": {"status": "unresolved", "reason": "no field calibration for SIM terms"},
        "window_days": days, "vapour_pressure_pa_abs": pv, "rim_kg": rim,
        "fitting_kg": fittings, "seam_proxy_kg": seam,
        "component_sum_kg": rim + fittings + seam,
        "parameter_hash": parameters.hash,
        "applicability_flags": ["unvalidated_simulation", "constant_conditions",
                                "suspension_and_seam_SIM", "withdrawal_not_included",
                                "not_facility_total", "not_liquid_mass_sink"],
    }


def roof_regime(level_m: float, parameters: Parameters) -> str:
    """Geometric roof regime from the existing calibrated support and draft model."""
    return load_tank_geometry().roof_state(level_m, parameters["density_kg_m3"])

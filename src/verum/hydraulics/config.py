"""Configuration of the steady-state hydraulics, as parameter records.

Inputs: ``config/hydraulics.json``, ``config/fitting_profiles.json`` and
``config/delivery_boundary.json``; the fluid contract for density, viscosity
and the vapor reference. Outputs: ``HydraulicConfig`` (scalar access to the
parameter records) and the loss-coefficient profile and boundary-law
coefficient for a named fitting profile.
Key assumptions:
    * Every number is a ``ParamValue``. Reading an unresolved one raises
      ``UnresolvedParameter``; nothing here supplies a default.
    * The boundary-law coefficient is looked up by fitting profile and is never
      a literal in code.
    * The solver tolerances are numerical settings, recorded as design values
      with their own provenance.

Source: ``revised/02_hydraulic_model.md`` sections 1.1, 3 and 4;
``docs/design_decisions.md`` D2 (version 3.0), D3, D7, D8, D11, D14 and D15.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from verum.contracts.errors import ContractError
from verum.contracts.paths import config_dir
from verum.hydraulics.volatility import derived_constants
from verum.params import ParamValue, ParamValueError


def _read(name: str, directory: Path | None) -> dict[str, Any]:
    path = (directory or config_dir()) / name
    try:
        loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read {path}: {exc}") from exc
    return loaded


def _records(raw: Mapping[str, Any]) -> dict[str, ParamValue]:
    try:
        return {k: ParamValue.from_mapping(v) for k, v in raw.items()}
    except ParamValueError as exc:
        raise ContractError(f"invalid parameter record: {exc}") from exc


@dataclass(frozen=True)
class HydraulicConfig:
    """Scalar parameters, property scenarios, temperature strata and taps."""

    parameters: dict[str, ParamValue]
    scenarios: dict[str, str]
    strata_c: dict[str, ParamValue]
    tap_reference_edges: dict[str, str]
    atmosphere_strata_pa_abs: dict[str, ParamValue] = field(default_factory=dict)
    derived_vapor_constants: dict[str, tuple[ParamValue, ParamValue]] = field(default_factory=dict)

    def __getitem__(self, name: str) -> float:
        try:
            return self.parameters[name].value
        except KeyError:
            raise ContractError(f"hydraulics config: no parameter {name!r}") from None

    def record(self, name: str) -> ParamValue:
        return self.parameters[name]

    def atmosphere_pa_abs(self, stratum: str) -> float:
        try:
            return self.atmosphere_strata_pa_abs[stratum].value
        except KeyError:
            raise ContractError(f"hydraulics config: no atmosphere stratum {stratum!r}") from None

    def temperature_c(self, stratum: str) -> float:
        try:
            return self.strata_c[stratum].value
        except KeyError:
            raise ContractError(f"hydraulics config: no temperature stratum {stratum!r}") from None


def load_hydraulic_config(directory: Path | None = None) -> HydraulicConfig:
    """Load ``config/hydraulics.json``."""
    raw = _read("hydraulics.json", directory)
    return HydraulicConfig(
        parameters=_records(raw["parameters"]),
        scenarios={
            k: v["fluid_contract_vapor_reference_id"] for k, v in raw["property_scenarios"].items()
        },
        strata_c=_records(raw["temperature_strata_c"]),
        tap_reference_edges=dict(raw["tap_reference_edges"]),
        atmosphere_strata_pa_abs=_records(raw.get("atmosphere_strata_pa_abs", {})),
        derived_vapor_constants=derived_constants(directory),
    )


@dataclass(frozen=True)
class FittingProfile:
    """Loss coefficients by element kind, with a global multiplier."""

    name: str
    coefficients: dict[str, ParamValue]
    multiplier: float = 1.0

    def k(self, kind: str) -> float:
        try:
            return self.coefficients[kind].value * self.multiplier
        except KeyError:
            raise ContractError(f"fitting profile {self.name}: no coefficient {kind!r}") from None


def load_fitting_profile(
    name: str, multiplier: float = 1.0, directory: Path | None = None
) -> FittingProfile:
    """Load a named fitting profile (decision D15)."""
    if multiplier < 0:
        raise ValueError("the K multiplier must not be negative")
    profiles = _read("fitting_profiles.json", directory)["profiles"]
    if name not in profiles:
        raise ContractError(f"unknown fitting profile {name!r}")
    return FittingProfile(name, _records(profiles[name]), multiplier)


def load_boundary_law_coefficient(profile: str, directory: Path | None = None) -> ParamValue:
    """Coefficient c (m) of the delivery boundary law for a fitting profile."""
    records = _records(_read("delivery_boundary.json", directory)["parameters"])
    if profile not in records:
        raise ContractError(f"no boundary-law coefficient for profile {profile!r}")
    return records[profile]

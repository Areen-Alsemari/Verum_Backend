"""Loader for the fluid contract.

The contract states a provisional simulation status, so its constants load as provisional with the
simulation evidence tag. The vapor-pressure reference constants come from a generic published
correlation and not from an assay of the product, and are tagged so that they are never mistaken for
resolved product properties. The vapor-pressure equation is kept as text and is evaluated elsewhere.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from verum.contracts.errors import ContractError
from verum.contracts.paths import config_dir
from verum.params import ParamValue, ParamValueError

FILENAME: Final = "fluid_contract.json"
_CONSTANTS: Final = (
    ("rho_kg_m3", "kg/m3"),
    ("mu_Pa_s", "Pa*s"),
    ("bulk_modulus_Pa", "Pa"),
    ("T_reference_K", "K"),
)
_VAPOR_CONSTANTS: Final = (
    ("A", "1"),
    ("B_degR", "degR"),
    ("vapor_molecular_weight_kg_kmol", "kg/kmol"),
)


@dataclass(frozen=True)
class FluidContract:
    """Fluid identity, constant-property reference values and vapor reference."""

    fluid_id: str
    model_status: str
    property_version: str
    properties: dict[str, ParamValue]
    vapor_reference_id: str
    vapor_constants: dict[str, ParamValue]
    vapor_pressure_equation: str


def _params(
    raw: dict[str, Any], names: tuple[tuple[str, str], ...], tag: str, provenance: str
) -> dict[str, ParamValue]:
    try:
        return {key: ParamValue.selected(raw[key], unit, tag, provenance) for key, unit in names}
    except (KeyError, ParamValueError) as exc:
        raise ContractError(f"fluid contract: invalid constant: {exc!r}") from exc


def parse_fluid_contract(contract: dict[str, Any]) -> FluidContract:
    """Validate a decoded fluid contract and convert its constants."""
    if contract.get("model_status") != "provisional_simulation":
        raise ContractError("fluid contract: model_status must be provisional_simulation")
    version = contract.get("property_version")
    if not isinstance(version, str) or not version:
        raise ContractError("fluid contract: property_version is required")
    vapor = contract.get("vapor_reference", {})
    vapor_id = vapor.get("id")
    if not isinstance(vapor_id, str) or not vapor_id:
        raise ContractError("fluid contract: vapor_reference.id is required")
    return FluidContract(
        fluid_id=str(contract.get("fluid_id", "")),
        model_status=contract["model_status"],
        property_version=version,
        properties=_params(contract, _CONSTANTS, "SIM", version),
        vapor_reference_id=vapor_id,
        vapor_constants=_params(vapor, _VAPOR_CONSTANTS, "REF", vapor_id),
        vapor_pressure_equation=str(vapor.get("true_vapor_pressure_equation_Pa", "")),
    )


def load_fluid_contract(directory: Path | None = None) -> FluidContract:
    """Load and validate the fluid contract."""
    path = (directory or config_dir()) / FILENAME
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read {path}: {exc}") from exc
    return parse_fluid_contract(decoded)

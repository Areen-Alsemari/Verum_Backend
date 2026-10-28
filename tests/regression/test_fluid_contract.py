"""Fluid contract: conversion into parameter records.

Inputs: ``config/fluid_contract.json`` and mutated copies.

Outputs: pass/fail.
Key assumptions: the constants are provisional simulation selections; the
vapor reference is a generic published correlation and is not promoted to a
resolved fuel property. No physics is evaluated here.

Source: ``fluid_contract.json``; ``revised/02_hydraulic_model.md`` section 1.1.
"""

from __future__ import annotations

from typing import Any

import pytest

from verum.contracts import ContractError, load_fluid_contract
from verum.contracts.fluid import parse_fluid_contract
from verum.params import ParamValue


def test_constants_are_provisional_simulation_values() -> None:
    fluid = load_fluid_contract()
    expected = {
        "rho_kg_m3": 750.0,
        "mu_Pa_s": 0.0005,
        "bulk_modulus_Pa": 1.0e9,
        "T_reference_K": 298.15,
    }
    assert {k: v.value for k, v in fluid.properties.items()} == expected
    for parameter in fluid.properties.values():
        assert (parameter.status, parameter.evidence_tag) == ("provisional", "SIM")
        assert parameter.provenance_id == "VERUM-PG95-SIM-1.0"


def test_vapor_reference_is_generic_and_not_resolved() -> None:
    fluid = load_fluid_contract()
    assert fluid.vapor_reference_id == "EPA_GENERIC_MOTOR_GASOLINE_RVP10"
    assert {k: v.value for k, v in fluid.vapor_constants.items()} == {
        "A": 11.724,
        "B_degR": 5237.3,
        "vapor_molecular_weight_kg_kmol": 66.0,
    }
    assert all(
        v.evidence_tag == "REF" and v.status == "provisional"
        for v in fluid.vapor_constants.values()
    )


def test_every_property_is_a_param_value() -> None:
    fluid = load_fluid_contract()
    assert all(
        isinstance(v, ParamValue)
        for v in (*fluid.properties.values(), *fluid.vapor_constants.values())
    )


def _break_status(c: dict[str, Any]) -> None:
    c["model_status"] = "validated"


def _drop_density(c: dict[str, Any]) -> None:
    del c["rho_kg_m3"]


def _string_density(c: dict[str, Any]) -> None:
    c["rho_kg_m3"] = "750"


def _no_version(c: dict[str, Any]) -> None:
    c["property_version"] = ""


def _no_vapor_id(c: dict[str, Any]) -> None:
    del c["vapor_reference"]["id"]


def _drop_vapor_constant(c: dict[str, Any]) -> None:
    del c["vapor_reference"]["B_degR"]


@pytest.mark.parametrize(
    "change",
    [
        _break_status,
        _drop_density,
        _string_density,
        _no_version,
        _no_vapor_id,
        _drop_vapor_constant,
    ],
)
def test_loader_rejects_incomplete_contract(raw_fluid: dict[str, Any], change: Any) -> None:
    change(raw_fluid)
    with pytest.raises(ContractError):
        parse_fluid_contract(raw_fluid)

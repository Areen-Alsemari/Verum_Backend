"""Parameter value: schema cases and agreement between the schema and the model.

Every case is run against both the schema and the in-code model, which must give the same verdict so
that the invariants in code cannot drift from the schema. The three known flaws of the original
fragment are rejected: a provisional value with no provenance, an unresolved value with a simulation
tag, and a resolved value tagged open.
"""

from __future__ import annotations

import dataclasses
import math
from typing import Any

import pytest

from verum.contracts import ContractError, validate, validator
from verum.params import ParamValue, ParamValueError, UnresolvedParameter

SELECTED: dict[str, Any] = {
    "value": 750.0,
    "unit": "kg/m3",
    "status": "provisional",
    "evidence_tag": "SIM",
    "provenance_id": "M2-SIM",
}
UNRESOLVED: dict[str, Any] = {
    "value": None,
    "unit": "m2",
    "status": "unresolved",
    "evidence_tag": "OPEN",
}


def _with(base: dict[str, Any], **changes: Any) -> dict[str, Any]:
    return {**base, **changes}


def _without(base: dict[str, Any], key: str) -> dict[str, Any]:
    return {k: v for k, v in base.items() if k != key}


CASES: list[tuple[str, dict[str, Any], bool]] = [
    ("provisional with provenance", SELECTED, True),
    ("resolved with provenance", _with(SELECTED, status="resolved", evidence_tag="REF"), True),
    ("unresolved open", UNRESOLVED, True),
    ("unresolved with reason", _with(UNRESOLVED, unresolved_reason="no assay"), True),
    ("provisional null provenance", _with(SELECTED, provenance_id=None), False),
    ("provisional missing provenance", _without(SELECTED, "provenance_id"), False),
    ("provisional empty provenance", _with(SELECTED, provenance_id=""), False),
    ("provisional null value", _with(SELECTED, value=None), False),
    ("unresolved tagged SIM", _with(UNRESOLVED, evidence_tag="SIM"), False),
    ("resolved tagged OPEN", _with(SELECTED, status="resolved", evidence_tag="OPEN"), False),
    ("provisional tagged OPEN", _with(SELECTED, evidence_tag="OPEN"), False),
    ("unresolved with zero", _with(UNRESOLVED, value=0), False),
    ("unresolved with string OPEN", _with(UNRESOLVED, value="OPEN"), False),
    ("string value", _with(SELECTED, value="750"), False),
    ("empty unit", _with(SELECTED, unit=""), False),
    ("missing unit", _without(SELECTED, "unit"), False),
    ("unknown status", _with(SELECTED, status="estimated"), False),
    ("unknown evidence tag", _with(SELECTED, evidence_tag="GUESS"), False),
    ("extra field", _with(SELECTED, note="x"), False),
]


@pytest.mark.parametrize(("name", "record", "expected"), CASES, ids=[c[0] for c in CASES])
def test_schema_verdict(name: str, record: dict[str, Any], expected: bool) -> None:
    """The schema accepts or rejects each case as expected. Independent: yes, because the verdicts
    are written out per case.
    """
    assert validator("paramvalue").is_valid(record) is expected


@pytest.mark.parametrize(("name", "record", "expected"), CASES, ids=[c[0] for c in CASES])
def test_model_agrees_with_schema(name: str, record: dict[str, Any], expected: bool) -> None:
    """The in-code model gives the same verdict as the schema for every case. Independent: yes,
    because the two implementations are compared with each other.
    """
    try:
        ParamValue.from_mapping(record)
    except ParamValueError:
        accepted = False
    else:
        accepted = True
    assert accepted is expected


def test_schema_error_is_reported_as_contract_error() -> None:
    """A schema violation is raised as the contract error. Independent: yes, because the expected
    outcome is the loader rule.
    """
    with pytest.raises(ContractError):
        validate("paramvalue", _with(SELECTED, provenance_id=None))


def test_unresolved_value_raises() -> None:
    """Reading the value of an unresolved parameter raises and shows the stated reason. Independent:
    yes, because the expected outcome is the rule that nothing replaces an unresolved parameter.
    """
    parameter = ParamValue.unresolved("m2", "leak area not selected")
    assert not parameter.is_resolved
    with pytest.raises(UnresolvedParameter, match="leak area not selected"):
        _ = parameter.value


def test_unresolved_from_mapping_raises_on_access() -> None:
    """An unresolved parameter built from a mapping raises when its value is read. Independent: yes,
    because the expected outcome is the same rule.
    """
    parameter = ParamValue.from_mapping(UNRESOLVED)
    with pytest.raises(UnresolvedParameter):
        _ = parameter.value


def test_provisional_value_is_readable() -> None:
    """A provisional parameter can be read. Independent: yes, because the expected value is the
    stored number.
    """
    parameter = ParamValue.from_mapping(SELECTED)
    assert parameter.is_resolved
    assert parameter.value == 750.0


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, True])
def test_model_rejects_non_quantities(bad: float) -> None:
    """Booleans and non-finite numbers are rejected as values. Independent: yes, because the
    expected outcome is the validation rule.
    """
    with pytest.raises(ParamValueError):
        ParamValue.selected(bad, "m", "SIM", "X")


def test_model_is_immutable() -> None:
    """A parameter record cannot be changed after it is built. Independent: yes, because the
    expected outcome is the immutability rule.
    """
    parameter = ParamValue.from_mapping(SELECTED)
    with pytest.raises(AttributeError):
        parameter.unit = "m"  # type: ignore[misc]


def test_stored_number_is_not_a_public_field() -> None:
    """The stored number is not a public field, so it can only be read through the checked accessor.
    Independent: yes, because the check lists the fields of the class.
    """
    # A public field named "value" would bypass the unresolved check on access.
    assert "value" not in {f.name for f in dataclasses.fields(ParamValue)}

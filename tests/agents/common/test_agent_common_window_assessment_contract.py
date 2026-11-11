"""Contract tests for the window assessment and the persistence fields."""

from __future__ import annotations

import copy
import json
from typing import Any

import jsonschema
import pytest

from verum.contracts.agent_interfaces import (
    contract_directory,
    validate_request,
    validate_response,
    validators,
)

pytestmark = pytest.mark.fast
IDS = ["R1_mass_balance", "R2_pump_head", "R3_discharge_loss", "R4_receipt_line"]
RULE = {"k": 2, "n": 3, "threshold": 1.8}
RECEIVERS = ("diagnostic_reasoning", "evidence_verification_decision")


def example(role: str, kind: str) -> dict[str, Any]:
    """A stored example message of a role."""
    path = contract_directory() / "examples" / f"{role}.{kind}.json"
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def assessment() -> dict[str, Any]:
    """A valid window assessment."""
    return {
        "score": 1.2, "window_threshold": 3.03, "exceeded": False, "complete": True,
        "persistence_rule": dict(RULE),
        "residuals": [{"residual_id": i, "state": "within_normal", "reason": None} for i in IDS],
    }  # fmt: skip


def response_with(item: dict[str, Any]) -> dict[str, Any]:
    """The stored Agent 2 response with an assessment added to its result."""
    response = copy.deepcopy(example("anomaly_detection", "response"))
    response["result"]["window_assessment"] = item
    return response


def test_old_agent_2_responses_without_an_assessment_still_validate() -> None:
    """The stored example response has no assessment and passes against its request.

    Independent: yes, because the example predates the optional field.
    """
    request = example("anomaly_detection", "request")
    response = example("anomaly_detection", "response")
    assert "window_assessment" not in response["result"]
    validate_response(request, response, validators())


@pytest.mark.parametrize("role", RECEIVERS)
def test_requests_without_the_new_fields_still_validate(role: str) -> None:
    """The stored requests of Agents 5 and 8 carry neither field and pass.

    Independent: yes, because the examples predate the optional fields.
    """
    request = example(role, "request")
    assert not {"recent_anomaly_assessments", "persistence"} & request["input"].keys()
    validate_request(request, validators())


def test_a_complete_assessment_validates() -> None:
    """An assessment with four residual entries in order is accepted.

    Independent: yes, because the validator is separate from the agent that writes it.
    """
    request = example("anomaly_detection", "request")
    validate_response(request, response_with(assessment()), validators())


@pytest.mark.parametrize(
    "damage",
    [
        lambda a: a.update(extra=1),
        lambda a: a["residuals"].pop(),
        lambda a: a["residuals"].reverse(),
        lambda a: a["residuals"][0].update(state="unknown"),
        lambda a: a["residuals"][0].update(state="healthy"),
        lambda a: a["persistence_rule"].update(k=0),
        lambda a: a.pop("complete"),
    ],
)
def test_a_damaged_assessment_is_refused(damage: Any) -> None:
    """Extra keys, a missing or reordered residual, a reasonless unknown and a bad rule fail.

    Independent: yes, because each damage breaks one stated rule of the schema.
    """
    item = assessment()
    damage(item)
    with pytest.raises(jsonschema.ValidationError):
        validate_response(
            example("anomaly_detection", "request"), response_with(item), validators()
        )


def test_an_unknown_residual_validates_with_a_reason() -> None:
    """The same unknown entry passes once it states why.

    Independent: yes, because the schema requires a reason only for the unknown state.
    """
    item = assessment()
    item["residuals"][1].update(state="unknown", reason="not computed: FT-201 has no value")
    validate_response(example("anomaly_detection", "request"), response_with(item), validators())


def persistence(alarming: bool | None, rule: dict[str, Any] | None, unknown: int) -> dict[str, Any]:
    """A persistence statement."""
    return {
        "rule": rule, "windows_held": 3, "windows_exceeding": 0, "windows_unknown": unknown,
        "alarming": alarming,
    }  # fmt: skip


@pytest.mark.parametrize("role", RECEIVERS)
def test_a_request_with_the_new_fields_validates(role: str) -> None:
    """Recent assessments and an unknown persistence statement are accepted.

    Independent: yes, because the validator checks the fields against the schema alone.
    """
    request = copy.deepcopy(example(role, "request"))
    as_of = request["context"]["as_of_s"]
    request["input"]["recent_anomaly_assessments"] = [
        {"as_of_s": as_of, "window_assessment": assessment()}
    ]
    request["input"]["persistence"] = persistence(None, dict(RULE), 1)
    validate_request(request, validators())


@pytest.mark.parametrize(
    "bad",
    [persistence(False, None, 0), persistence(False, dict(RULE), 1), persistence(True, None, 0)],
)
def test_alarming_true_or_false_needs_the_rule_and_false_needs_known_windows(
    bad: dict[str, Any],
) -> None:
    """False with an unknown window, or true or false without a rule, is refused.

    Independent: yes, because unknown must never be reported as false.
    """
    request = copy.deepcopy(example("diagnostic_reasoning", "request"))
    request["input"]["persistence"] = bad
    with pytest.raises(jsonschema.ValidationError):
        validate_request(request, validators())


def test_recent_assessments_must_be_past_and_in_order() -> None:
    """An assessment later than the cutoff, or out of order, is refused.

    Independent: yes, because a request may not carry content from after its cutoff.
    """
    request = copy.deepcopy(example("diagnostic_reasoning", "request"))
    as_of = request["context"]["as_of_s"]
    rows = [{"as_of_s": as_of + 1.0, "window_assessment": None}]
    request["input"]["recent_anomaly_assessments"] = rows
    with pytest.raises(ValueError, match="later than the request cutoff"):
        validate_request(request, validators())
    rows = [
        {"as_of_s": as_of, "window_assessment": None},
        {"as_of_s": as_of - 1.0, "window_assessment": None},
    ]
    request["input"]["recent_anomaly_assessments"] = rows
    with pytest.raises(ValueError, match="not ordered"):
        validate_request(request, validators())

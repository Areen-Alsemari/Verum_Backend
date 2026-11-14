"""Tests for the window assessment that Agent 2 adds to its result, on synthetic windows."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from _anomaly_cases import healthy, parameters, request_with
from verum.agents.anomaly_detection import AnomalyDetectionAgent
from verum.agents.anomaly_detection import agent as anomaly_agent
from verum.agents.common import check_request, check_response

pytestmark = pytest.mark.fast
IDS = ["R1_mass_balance", "R2_pump_head", "R3_discharge_loss", "R4_receipt_line"]
RULE = {"k": 2, "n": 3, "threshold": 1.5}


@pytest.fixture(autouse=True)
def synthetic_parameters(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Run on the round-number parameters: thresholds 1.0 per residual, 3.0 for the window."""
    params = parameters(tmp_path)
    monkeypatch.setattr(anomaly_agent, "load_parameters", lambda: params)


def run(values: Mapping[str, float | None]) -> dict[str, Any]:
    """Run the agent on the example request with the given inputs and validate both sides."""
    request = request_with(values)
    check_request(request)
    response = AnomalyDetectionAgent().run(request)
    check_response(request, response)
    return response


def states(response: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The residual entries of the assessment by identifier."""
    return {r["residual_id"]: r for r in response["result"]["window_assessment"]["residuals"]}


def event_ids(response: dict[str, Any]) -> set[str]:
    """Residual identifiers that have a residual event."""
    keys = {e["event_id"].rsplit("-", 1)[1] for e in response["result"]["events"]}
    return {i for i in IDS if i.split("_")[0] in keys}


def test_a_healthy_window_is_assessed_within_normal_with_the_published_rule() -> None:
    """Every residual is within normal, the score is zero and the rule is the one in the file.

    Independent: yes, because the window is built so that every residual is exactly zero.
    """
    assessment = run(healthy("A"))["result"]["window_assessment"]
    assert assessment["score"] == pytest.approx(0.0, abs=1e-9)
    assert assessment["window_threshold"] == 3.0 and assessment["exceeded"] is False
    assert assessment["complete"] is True and assessment["persistence_rule"] == RULE
    assert [r["residual_id"] for r in assessment["residuals"]] == IDS
    assert all(
        r["state"] == "within_normal" and r["reason"] is None for r in assessment["residuals"]
    )


@pytest.mark.parametrize(
    ("shift", "exceeded"),
    [
        ({"PT-203": 1.0}, {"R3_discharge_loss"}),
        ({"PT-001": 0.5}, {"R4_receipt_line"}),
        ({"PT-201": 1.0}, {"R2_pump_head"}),
        ({"LT-101": 0.001}, {"R1_mass_balance"}),
        ({}, set()),
    ],
)
def test_a_residual_is_exceeded_exactly_when_it_has_an_event(
    shift: dict[str, float], exceeded: set[str]
) -> None:
    """The states of the assessment and the residual events name the same residuals.

    Independent: yes, because the moved tag decides by hand which residual is expected to exceed.
    """
    values = healthy("A")
    values.update({tag: (values[tag] or 0.0) + delta for tag, delta in shift.items()})
    response = run(values)
    got = {i for i, r in states(response).items() if r["state"] == "exceeded"}
    assert got == exceeded == event_ids(response)


def test_an_unknown_residual_is_never_within_normal_and_says_why() -> None:
    """Without FT-201, R1, R2 and R3 are unknown with a reason; only R4 is within normal.

    Independent: yes, because FT-201 is read by R1, R2 and R3 and not by R4.
    """
    response = run(healthy("A") | {"FT-201": None})
    found = states(response)
    for name in ("R1_mass_balance", "R2_pump_head", "R3_discharge_loss"):
        assert found[name]["state"] == "unknown" and "FT-201" in found[name]["reason"]
    assert found["R4_receipt_line"]["state"] == "within_normal"
    assert response["result"]["window_assessment"]["complete"] is False
    assert event_ids(response) == set()


def test_a_residual_that_does_not_apply_is_unknown_and_the_window_stays_complete() -> None:
    """With no pump running R2 and R3 are unknown (not applicable) and nothing is missing.

    Independent: yes, because the pump residuals do not apply when no pump runs.
    """
    response = run(healthy("A") | {"P-101A": 0.0})
    found = states(response)
    assert found["R2_pump_head"]["state"] == found["R3_discharge_loss"]["state"] == "unknown"
    assert found["R2_pump_head"]["reason"].startswith("not applicable")
    assert response["result"]["window_assessment"]["complete"] is True


def test_the_window_flag_follows_the_strict_comparison_with_the_threshold() -> None:
    """A score equal to the window threshold is not exceeded; a larger one is.

    Independent: yes, because (8 - 2) / 2 equals the window threshold of 3.0 exactly.
    """
    at_threshold = run(healthy("A") | {"FT-001": 408.0})["result"]["window_assessment"]
    above = run(healthy("A") | {"FT-001": 409.0})["result"]["window_assessment"]
    assert (at_threshold["score"], at_threshold["exceeded"]) == (3.0, False)
    assert above["score"] > 3.0 and above["exceeded"] is True


def test_no_assessment_when_the_status_is_insufficient_evidence() -> None:
    """With nothing computable the result is null, so there is no assessment.

    Independent: yes, because R1 and R4 both read FT-001 and R2 and R3 do not apply.
    """
    response = run(healthy("A") | {"P-101A": 0.0, "FT-001": None})
    assert response["status"] == "insufficient_evidence" and response["result"] is None


def test_the_assessment_is_deterministic() -> None:
    """The same request gives the same bytes, assessment included.

    Independent: yes, because the check compares two runs of one input.
    """
    request = request_with(healthy("A") | {"PT-203": 3.0})
    first = json.dumps(AnomalyDetectionAgent().run(request), sort_keys=True)
    second = json.dumps(AnomalyDetectionAgent().run(request), sort_keys=True)
    assert first == second and "window_assessment" in first

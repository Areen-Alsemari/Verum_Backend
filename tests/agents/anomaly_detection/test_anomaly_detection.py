"""Tests for the Anomaly Detection agent runtime with the topology residual detector."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from _anomaly_cases import healthy, parameters, rehash, request_with, set_missing
from verum.agents.anomaly_detection import AnomalyDetectionAgent
from verum.agents.anomaly_detection import agent as anomaly_agent
from verum.agents.common import check_request, check_response
from verum.contracts.agent_interfaces import content_hash, contract_directory

pytestmark = pytest.mark.fast


@pytest.fixture(autouse=True)
def synthetic_parameters(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Run the agent on the round-number parameters so every expectation is worked by hand."""
    params = parameters(tmp_path)
    monkeypatch.setattr(anomaly_agent, "load_parameters", lambda: params)


def run(values: Mapping[str, float | None]) -> dict[str, Any]:
    """Run the agent on the example request with the given inputs and validate both sides."""
    request = request_with(values)
    check_request(request)
    response = AnomalyDetectionAgent().run(request)
    check_response(request, response)
    return response


def residual_events(response: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Residual events by residual key."""
    events = response["result"]["events"]
    return {e["event_id"].rsplit("-", 1)[1]: e for e in events if "-residual-" in e["event_id"]}


def test_a_healthy_window_is_complete_and_has_no_residual_event() -> None:
    """A healthy window with a running pump is complete, assessed and has no residual event.

    Independent: yes, because the window is built to give zero for every residual.
    """
    response = run(healthy("A"))
    assert (response["status"], response["result"]["coverage"]) == ("complete", "assessed")
    assert residual_events(response) == {}
    assert response["result"]["no_event_means_healthy"] is False
    assert any("not exceeded" in line for line in response["limitations"])


def test_a_residual_above_its_threshold_gives_one_event_naming_its_tags() -> None:
    """A rise of PT-203 moves R3 only; its event names the tags R3 reads and no others.

    Independent: yes, because the tags R3 reads are listed in the plan.
    """
    response = run(healthy("A") | {"PT-203": healthy("A")["PT-203"] + 1.0})
    events = residual_events(response)
    assert set(events) == {"R3"}
    event = events["R3"]
    assert event["tag_ids"] == ["FT-201", "P-101A", "PT-202A", "PT-203"]
    assert event["asset_ids"] == []
    assert event["category"] == "reported_signal_departure"
    assert event["method_id"] == "topology_residual_v1"
    assert event["score"]["kind"] == "decision_score"
    assert event["score"]["value"] == pytest.approx(19.0)


@pytest.mark.parametrize(
    ("pump", "tags"),
    [
        ("A", ["FT-201", "P-101A", "PT-201", "PT-202A"]),
        ("B", ["FT-201", "P-101B", "PT-201", "PT-202B"]),
    ],
)
def test_the_pump_residual_names_only_the_running_pump(pump: str, tags: list[str]) -> None:
    """R2 names the running pump's discharge and run-state tags and not the other pump's.

    Independent: yes, because the tags follow from which pump is running in the built window.
    """
    response = run(healthy(pump) | {"PT-201": 3.0})
    assert residual_events(response)["R2"]["tag_ids"] == tags


def test_the_mass_imbalance_event_names_the_candidates_and_no_asset() -> None:
    """The R1 event says a leak, a flow-meter fault or a level-sensor fault are candidates.

    Independent: yes, because the required wording is stated in the task.
    """
    event = residual_events(run(healthy("A") | {"FT-201": 380.0}))["R1"]
    words = " ".join(event["limitations"]).lower()
    assert "mass imbalance" in words and "leak" in words
    assert "flow-meter" in words and "level-sensor" in words
    assert event["tag_ids"] == ["FT-001", "FT-201", "LT-101", "LT-102", "LT-103"]
    assert "no asset, location or fault type" in words


def test_a_residual_at_exactly_its_own_threshold_gives_no_event() -> None:
    """A residual of 4 with scale 2 is 1.0 scale unit past the dead zone, equal to its threshold.

    Independent: yes, because (4 - 2) / 2 equals the test threshold of 1.0 exactly.
    """
    assert residual_events(run(healthy("A") | {"FT-001": 404.0})) == {}
    assert set(residual_events(run(healthy("A") | {"FT-001": 404.5}))) == {"R1"}


def test_the_window_score_is_not_exceeded_at_exactly_the_threshold() -> None:
    """A score equal to the window threshold is not exceeded, as in the registered rule.

    Independent: yes, because (8 - 2) / 2 equals the test threshold of 3.0 exactly.
    """
    response = run(healthy("A") | {"FT-001": 408.0})
    joined = " ".join(response["limitations"])
    assert "Window score 3.00" in joined and "3.00: not exceeded" in joined
    assert "R1" in residual_events(response)


def test_missing_inputs_give_a_degraded_window_with_unknown_residuals_listed() -> None:
    """Without FT-001, R1 and R4 are unknown, the status is degraded and the issue names them.

    Independent: yes, because the dependencies are listed in the plan.
    """
    response = run(healthy("A") | {"FT-001": None})
    assert (response["status"], response["result"]["coverage"]) == ("degraded", "partial")
    issue = next(i for i in response["issues"] if i["code"] == "INSUFFICIENT_EVIDENCE")
    assert "unknown, not zero" in issue["message"]
    assert "unknown: R1, R4" in issue["message"] and "FT-001" in issue["message"]
    assert "Residuals computed: R2, R3; unknown: R1, R4" in " ".join(response["limitations"])


def test_an_unknown_residual_never_hides_behind_zero() -> None:
    """An extreme R3 is still reported when R1 is unknown; the unknown R1 gives no event.

    Independent: yes, because the window is built so that only R3 moves.
    """
    values = healthy("A") | {"FT-001": None, "PT-203": healthy("A")["PT-203"] + 1.0}
    events = residual_events(run(values))
    assert set(events) == {"R3"}


def test_no_computable_residual_is_insufficient_evidence() -> None:
    """With no pump running and no receipt flow, nothing can be computed.

    Independent: yes, because R1 and R4 both read FT-001 and R2 and R3 do not apply.
    """
    values = healthy("A") | {"P-101A": 0.0, "FT-001": None}
    response = run(values)
    assert response["status"] == "insufficient_evidence" and response["result"] is None
    issue = response["issues"][0]
    assert (
        issue["code"] == "INSUFFICIENT_EVIDENCE"
        and "No residual could be computed" in issue["message"]
    )


def test_no_pump_running_is_complete_with_r1_and_r4_only() -> None:
    """With neither pump on, R1 and R4 are enough: the window is complete and says so.

    Independent: yes, because R2 and R3 do not apply when no pump runs.
    """
    response = run(healthy("A") | {"P-101A": 0.0})
    assert response["status"] == "complete"
    assert "computed: R1, R4; not applicable: R2, R3" in " ".join(response["limitations"])


def test_a_wrong_unit_is_excluded_and_reported() -> None:
    """A signal with an unexpected unit is unknown for the residuals that read it.

    Independent: yes, because the unit of FT-001 is changed to one the detector does not accept.
    """
    request = request_with(healthy("A"))
    signals = request["input"]["observations"]["summary"]["signals"]
    next(s for s in signals if s["tag_id"] == "FT-001")["unit"] = "m"
    rehash(request)
    response = AnomalyDetectionAgent().run(request)
    assert response["status"] == "degraded"
    assert "INVALID_SIGNAL_UNIT" in {i["code"] for i in response["issues"]}
    assert "unit 'm' where 'm3/h' is expected" in response["issues"][-1]["message"]


def test_quality_events_are_kept_and_sorted() -> None:
    """Missing readings and non-good quality are reported as before, with sorted tags.

    Independent: yes, because the flags are set on two signals in the test.
    """
    request = request_with(healthy("A"))
    signals = request["input"]["observations"]["summary"]["signals"]
    by_tag = {s["tag_id"]: s for s in signals}
    set_missing(by_tag["TT-103"], 2)
    set_missing(by_tag["TT-101"], 1)
    by_tag["PT-203"]["latest_quality"] = "bad"
    rehash(request)
    events = AnomalyDetectionAgent().run(request)["result"]["events"]
    kinds = {e["category"]: e["tag_ids"] for e in events}
    assert kinds["missing_reading"] == ["TT-101", "TT-103"]
    assert kinds["non_good_quality"] == ["PT-203"]


def test_the_fixed_flags_and_the_response_stay_advisory() -> None:
    """The response is advisory, never says no event means healthy, carries no authorisation.

    Independent: yes, because the required values are stated in the contract.
    """
    response = run(healthy("A") | {"FT-201": 380.0})
    assert response["advisory_only"] is True
    assert response["result"]["no_event_means_healthy"] is False
    text = json.dumps(response)
    for forbidden in ("human_decision_required", "automatic_action_authorized"):
        assert forbidden not in text
    assert "No detected event does not establish healthy equipment." in response["limitations"]


def test_the_same_request_gives_the_same_bytes() -> None:
    """Two runs on equal requests, healthy, flagged and degraded, give identical bytes.

    Independent: yes, because the comparison is of serialised output against itself.
    """
    for values in (healthy("A"), healthy("A") | {"FT-201": 380.0}, healthy("A") | {"FT-001": None}):
        request = request_with(values)
        first = json.dumps(AnomalyDetectionAgent().run(copy.deepcopy(request)))
        second = json.dumps(AnomalyDetectionAgent().run(copy.deepcopy(request)))
        assert first == second


def test_a_sequence_request_is_not_supported() -> None:
    """A sequence_v1 request returns an error response that names the representation.

    Independent: yes, because the request is built by hand with one sample per channel.
    """
    request = copy.deepcopy(request_with(healthy("A")))
    summary = request["input"]["observations"]["summary"]
    sequence = {
        "lookback_s": 300.0,
        "channels": [
            {
                "tag_id": s["tag_id"],
                "unit": s["unit"],
                "samples": [
                    {
                        "available_offset_s": -1.0,
                        "measured_offset_s": -1.0,
                        "value": 1.0,
                        "quality_flag": "good",
                        "availability_status": "measured",
                    }
                ],
            }  # fmt: skip
            for s in summary["signals"]
        ],
    }
    observations = request["input"]["observations"]
    request["input"]["observations"] = {
        "representation": "sequence_v1", "sequence": sequence,
        "evidence_ids": observations["evidence_ids"],
    }  # fmt: skip
    for row in request["evidence"]:
        if row["evidence_id"] in observations["evidence_ids"]:
            row["content_sha256"] = content_hash(sequence)
    check_request(request)
    response = AnomalyDetectionAgent().run(request)
    assert response["status"] == "error" and response["result"] is None
    assert response["issues"][0]["code"] == "UNSUPPORTED_OBSERVATION_REPRESENTATION"


def test_an_unverifiable_parameter_file_leaves_only_the_quality_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the parameters cannot be loaded the agent names the problem and runs the rules only.

    Independent: yes, because the loader is made to refuse and the outcome is read from the output.
    """

    def refuse() -> Any:
        raise ValueError("topology residual parameter file hash mismatch")

    monkeypatch.setattr(anomaly_agent, "load_parameters", refuse)
    request = request_with(healthy("A"))
    response = AnomalyDetectionAgent().run(request)
    check_response(request, response)
    assert response["status"] == "degraded"
    assert "MODEL_UNAVAILABLE" in {i["code"] for i in response["issues"]}
    assert response["result"]["coverage"] == "partial"
    assert residual_events(response) == {}


def test_the_contract_example_request_passes_with_the_shipped_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The official example is answered, with a valid response, on the shipped parameters.

    Independent: yes, because validity is judged by the contract validators.
    """
    monkeypatch.undo()
    path = contract_directory() / "examples" / "anomaly_detection.request.json"
    request = json.loads(path.read_text(encoding="utf-8"))
    response = AnomalyDetectionAgent().run(request)
    check_response(request, response)
    assert response["implementation"]["name"] == "anomaly_detection"
    assert response["implementation"]["artifact_sha256"] is not None


def test_consumed_evidence_matches_the_request_and_the_forecast_is_kept() -> None:
    """The observation evidence is consumed, and an attached forecast report is consumed too.

    Independent: yes, because the ids come from the request the test built.
    """
    request = request_with(healthy("A"))
    response = AnomalyDetectionAgent().run(request)
    assert response["consumed_evidence_ids"] == request["input"]["observations"]["evidence_ids"]
    assert "Forecast reports are not used as model features." in response["limitations"]


def test_an_invalid_request_returns_an_error_response() -> None:
    """A request that fails the contract returns an error response, not an exception.

    Independent: yes, because the request is broken by hand.
    """
    request = request_with(healthy("A"))
    request["interface_version"] = "bad"
    response = AnomalyDetectionAgent().run(request)
    assert response["status"] == "error" and response["result"] is None


def test_an_internal_failure_returns_a_validated_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unexpected exception inside the analysis becomes a validated error response.

    Independent: yes, because the failure is injected and the output is judged by the validators.
    """

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("injected")

    monkeypatch.setattr(anomaly_agent, "run_detector", boom)
    request = request_with(healthy("A"))
    response = AnomalyDetectionAgent().run(request)
    check_response(request, response)
    assert response["status"] == "error"
    assert response["issues"][0]["code"] == "INTERNAL_ERROR"

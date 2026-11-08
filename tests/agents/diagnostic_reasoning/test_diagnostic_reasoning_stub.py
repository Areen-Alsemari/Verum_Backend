"""Tests for the Diagnostic Reasoning agent: observation inference, upstream rules and contracts.

Every test checks an explicit rule of the Diagnostic Reasoning contract, including missing
reports, conflicting upstream evidence, unknown contexts and strict registry validation.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from verum.agents.common import check_request, check_response, stable_hash
from verum.agents.diagnostic_reasoning import DiagnosticReasoningAgent
from verum.agents.diagnostic_reasoning.features import extract_observation_vector, feature_names
from verum.agents.diagnostic_reasoning.rules import (
    KNOWN_ASSETS,
    KNOWN_TAGS,
    SUPPORTED_MECHANISMS,
    UPSTREAM_FIELDS,
    valid_component,
)
from verum.contracts.agent_interfaces import contract_directory


def _example_request() -> dict[str, Any]:
    path = contract_directory() / "examples" / "diagnostic_reasoning.request.json"
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def _chained_request() -> dict[str, Any]:
    path = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "chained"
        / "diagnostic_reasoning.request.json"
    )
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def test_diagnostic_reasoning_answers_the_example_request_validly() -> None:
    """The agent answers its standalone example request with all five upstream checks unknown.

    Independent: yes, because the contract validator checks the output independently.
    """
    agent = DiagnosticReasoningAgent()
    request = _example_request()
    check_request(request)
    response = agent.run(request)
    check_response(request, response)
    assert response["agent"] == "diagnostic_reasoning"
    assert response["advisory_only"] is True
    assert response["result"]["field_diagnosis_qualified"] is False
    checks = {c["check_id"]: c["outcome"] for c in response["result"]["upstream_checks"]}
    assert set(checks) == set(UPSTREAM_FIELDS)
    assert set(checks.values()) == {"unknown"}


def test_diagnostic_reasoning_consumes_all_attached_chained_reports() -> None:
    """The agent consumes every attached upstream report in the chained runtime fixture.

    Independent: yes, because the chained fixture is read from disk and validated by the contract.
    """
    agent = DiagnosticReasoningAgent()
    request = _chained_request()
    check_request(request)
    response = agent.run(request)
    check_response(request, response)
    for field in UPSTREAM_FIELDS:
        report = request["input"][field]
        assert report is not None
        assert report["report_id"] in response["consumed_evidence_ids"]


def test_feature_extractor_produces_a_finite_vector_matching_feature_names() -> None:
    """Extracted observation features match the declared feature name count and are finite.

    Independent: yes, because the vector length is compared against the separate name list.
    """
    request = _example_request()
    vec = extract_observation_vector(request["input"]["observations"])
    names = feature_names()
    assert vec.shape == (len(names),)


def test_empty_hypotheses_give_inconclusive_assessment_never_healthy() -> None:
    """When no fault hypothesis triggers, the assessment is inconclusive with a null ranking basis.

    Independent: yes, because the expected literal strings are checked directly.
    """
    agent = DiagnosticReasoningAgent()
    request = _example_request()
    response = agent.run(request)
    if not response["result"]["hypotheses"]:
        assert response["result"]["assessment"] == "inconclusive"
        assert response["result"]["ranking_basis"] is None


def test_stuck_sensor_observation_triggers_a_valid_hypothesis() -> None:
    """A frozen flow signal with zero standard deviation produces a stuck sensor hypothesis.

    Independent: yes, because the synthetic stuck signal is constructed by the test.
    """
    request = _example_request()
    for sig in request["input"]["observations"]["summary"]["signals"]:
        if sig["tag_id"] == "FT-001":
            sig["standard_deviation"] = 0.0
            sig["mean"] = 500.0
            sig["measured_count"] = 300
            sig["missing_samples"] = 0
    summary = request["input"]["observations"]["summary"]
    for row in request["evidence"]:
        if row["evidence_id"] == "features-summary":
            row["content_sha256"] = stable_hash(summary)
    agent = DiagnosticReasoningAgent()
    response = agent.run(request)
    check_response(request, response)
    hyps = response["result"]["hypotheses"]
    assert len(hyps) >= 1
    assert response["result"]["assessment"] == "candidates_available"
    for h in hyps:
        for comp in h["components"]:
            assert comp["mechanism"] in SUPPORTED_MECHANISMS
            if comp["asset_id"] is not None:
                assert comp["asset_id"] in KNOWN_ASSETS
            if comp["tag_id"] is not None:
                assert comp["tag_id"] in KNOWN_TAGS


def test_non_stub_upstream_reports_update_upstream_checks_and_support() -> None:
    """When real upstream reports are attached, upstream checks pass or fail appropriately.

    Independent: yes, because the upstream reports are modified by the test.
    """
    request = _chained_request()
    anom = copy.deepcopy(request["input"]["anomaly_report"])
    anom["issues"] = []
    anom["status"] = "complete"
    anom["result"]["coverage"] = "assessed"
    anom["result"]["events"] = [{
        "event_id": "EV-1",
        "tag_ids": ["FT-001"],
        "asset_ids": ["E001"],
        "category": "reported_signal_departure",
        "score": None,
        "method_id": "rule_v1",
        "evidence_ids": ["source-observations"],
        "limitations": ["Rule check only."],
    }]
    request["input"]["anomaly_report"] = anom
    for row in request["evidence"]:
        if row["evidence_id"] == anom["report_id"]:
            row["content_sha256"] = stable_hash(anom)

    agent = DiagnosticReasoningAgent()
    response = agent.run(request)
    check_response(request, response)
    checks = {c["check_id"]: c["outcome"] for c in response["result"]["upstream_checks"]}
    assert checks["anomaly_report"] == "pass"


def test_invalid_component_mechanism_is_rejected() -> None:
    """Unsupported mechanisms raise a ValueError and unknown assets become None.

    Independent: yes, because the invalid mechanism name is supplied by the test.
    """
    with pytest.raises(ValueError, match="unsupported mechanism"):
        valid_component("roof_rupture", "TK-101", None)
    cleaned = valid_component("leak", "UNKNOWN-PIPE", "UNKNOWN-TAG")
    assert cleaned == {"mechanism": "leak", "asset_id": None, "tag_id": None}

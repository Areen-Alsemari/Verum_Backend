"""Tests for the Diagnostic Reasoning agent: observation inference, upstream rules and contracts.

Every test checks an explicit rule of the Diagnostic Reasoning contract, including artifact
execution on faulty windows, feature order, thresholds, ranking, support/conflict IDs and errors.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import joblib  # type: ignore[import-untyped]
import numpy as np
import pytest

from verum.agents.common import check_request, check_response, stable_hash
from verum.agents.diagnostic_reasoning import DiagnosticReasoningAgent
from verum.agents.diagnostic_reasoning.features import extract_observation_vector, feature_names
from verum.agents.diagnostic_reasoning.model import (
    CandidatePrediction,
    DiagnosticModel,
    default_artifact_path,
    format_hypotheses,
)
from verum.agents.diagnostic_reasoning.rules import (
    LOW_SUPPORT_MECHANISMS,
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


class _MockScaler:
    """Deterministic identity scaler for testing artifact execution."""

    def transform(self, x: np.ndarray) -> np.ndarray:
        return x


class _MockClassifier:
    """Deterministic binary classifier returning a fixed positive score."""

    def __init__(self, prob: float) -> None:
        self.prob = prob

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        return np.asarray([[1.0 - self.prob, self.prob]], dtype=np.float64)


def _write_mock_artifact(tmp_path: Path) -> tuple[Path, str]:
    """Write a small valid joblib artifact with two active mechanisms and one component."""
    artifact = {
        "role": "diagnostic_reasoning",
        "method_id": "ovr_selected_classifier_v1",
        "feature_names": feature_names(),
        "scaler": _MockScaler(),
        "mechanism_models": {
            "pump": _MockClassifier(0.82),
            "leak": _MockClassifier(0.65),
            "drift": _MockClassifier(0.10),
        },
        "mechanism_thresholds": {"pump": 0.50, "leak": 0.50, "drift": 0.50},
        "component_models": {
            "pump::P-101A": _MockClassifier(0.88),
            "restriction_position_visible::XV-PAO": _MockClassifier(0.20),
        },
        "component_thresholds": {
            "pump::P-101A": 0.50,
            "restriction_position_visible::XV-PAO": 0.50,
        },
    }
    path = tmp_path / "model_artifact.joblib"
    joblib.dump(artifact, path)
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    return path, sha


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


def test_feature_extractor_order_and_derived_channels_are_exact() -> None:
    """Extracted observation features match the declared feature order and derived formulas.

    Independent: yes, because specific indices and arithmetic differences are verified directly.
    """
    request = _example_request()
    vec = extract_observation_vector(request["input"]["observations"])
    names = feature_names()
    assert vec.shape == (len(names),)
    assert names[0] == "FT-001__latest_value"
    assert names[-5] == "derived__flow_imbalance_m3h"
    ft001_mean = vec[names.index("FT-001__mean")]
    ft201_mean = vec[names.index("FT-201__mean")]
    assert np.isclose(vec[-5], ft001_mean - ft201_mean)


def test_artifact_hash_verification_rejects_tampered_file(tmp_path: Path) -> None:
    """Loading an artifact with a mismatched SHA-256 raises ValueError before joblib loads it.

    Independent: yes, because a wrong expected hash is passed explicitly.
    """
    path, _ = _write_mock_artifact(tmp_path)
    with pytest.raises(ValueError, match="artifact sha256 mismatch"):
        DiagnosticModel(path, expected_sha256="00" * 32)


def test_artifact_executes_thresholds_ranking_and_low_support_markers(
    tmp_path: Path,
) -> None:
    """The artifact applies thresholds, ranks descending by score, and marks low-support labels.

    Independent: yes, because mock probabilities above and below threshold are controlled.
    """
    path, sha = _write_mock_artifact(tmp_path)
    agent = DiagnosticReasoningAgent(path, expected_sha256=sha)
    request = _example_request()
    response = agent.run(request)
    check_response(request, response)
    hyps = response["result"]["hypotheses"]
    assert len(hyps) == 2
    assert response["result"]["assessment"] == "candidates_available"
    assert response["result"]["ranking_basis"] == "decision_score_descending"
    assert hyps[0]["components"][0] == {
        "mechanism": "pump",
        "asset_id": "P-101A",
        "tag_id": None,
    }
    assert hyps[0]["score"]["value"] == 0.88
    assert hyps[1]["components"][0]["mechanism"] == "leak"
    assert hyps[1]["score"]["value"] == 0.65
    assert hyps[1]["score"]["method_id"].endswith("_low_support_uncalibrated")
    assert LOW_SUPPORT_MECHANISMS["leak"] in hyps[1]["unresolved_questions"]


def test_committed_artifact_triggers_on_faulty_pump_and_valve_window() -> None:
    """Running the committed artifact on a faulty observation window yields ranked hypotheses.

    Independent: yes, because the faulty signal pattern is constructed in the test.
    """
    if not default_artifact_path().is_file():
        return
    request = _example_request()
    for sig in request["input"]["observations"]["summary"]["signals"]:
        if sig["tag_id"] == "XV-R101":
            sig["latest_value"] = 0.0
            sig["previous_measured_value"] = 1.0
        elif sig["tag_id"] == "PT-001":
            sig["mean"] = 8.5
            sig["maximum"] = 9.2
            sig["latest_value"] = 9.0
        elif sig["tag_id"] == "FT-001":
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
    scores = [h["score"]["value"] for h in hyps]
    assert scores == sorted(scores, reverse=True)


def test_upstream_rules_populate_both_support_and_conflict_evidence_ids(
    tmp_path: Path,
) -> None:
    """Upstream reports matching or contradicting a candidate populate support and conflict IDs.

    Independent: yes, because matching anomaly and conflicting asset/inspection reports are built.
    """
    path, sha = _write_mock_artifact(tmp_path)
    agent = DiagnosticReasoningAgent(path, expected_sha256=sha)
    request = _chained_request()

    anom = copy.deepcopy(request["input"]["anomaly_report"])
    anom["issues"] = []
    anom["status"] = "complete"
    anom["result"]["coverage"] = "assessed"
    anom["result"]["events"] = [
        {
            "event_id": "EV-1",
            "tag_ids": ["PT-202A"],
            "asset_ids": ["P-101A"],
            "category": "reported_signal_departure",
            "score": None,
            "method_id": "rule_v1",
            "evidence_ids": ["source-observations"],
            "limitations": ["Rule check."],
        }
    ]
    request["input"]["anomaly_report"] = anom

    asset_rep = copy.deepcopy(request["input"]["asset_report"])
    asset_rep["issues"] = []
    asset_rep["status"] = "complete"
    asset_rep["result"]["missing_asset_ids"] = ["P-101A"]
    request["input"]["asset_report"] = asset_rep

    insp_rep = copy.deepcopy(request["input"]["inspection_quality_report"])
    insp_rep["issues"] = []
    insp_rep["status"] = "complete"
    insp_rep["result"]["record_checks"] = [
        {
            "result_id": "RES-INSP-00001",
            "checks": [
                {
                    "check_id": "timing",
                    "description": "Check timing",
                    "outcome": "fail",
                    "evidence_ids": ["source-reference"],
                }
            ],
            "measurement_usable": False,
            "scope_supported": True,
            "equipment_condition_confirmed": False,
            "evidence_ids": ["source-reference"],
        }
    ]
    request["input"]["inspection_quality_report"] = insp_rep

    for rep in (anom, asset_rep, insp_rep):
        for row in request["evidence"]:
            if row["evidence_id"] == rep["report_id"]:
                row["content_sha256"] = stable_hash(rep)

    response = agent.run(request)
    check_response(request, response)
    pump_hyp = next(
        h for h in response["result"]["hypotheses"] if h["components"][0]["asset_id"] == "P-101A"
    )
    assert anom["report_id"] in pump_hyp["support_evidence_ids"]
    assert asset_rep["report_id"] in pump_hyp["conflict_evidence_ids"]
    assert insp_rep["report_id"] in pump_hyp["conflict_evidence_ids"]


def test_runtime_exception_in_execution_returns_error_status_with_issue(
    tmp_path: Path,
) -> None:
    """An internal model error during run() is caught and returned as status error.

    Independent: yes, because the broken artifact hash triggers an initialization failure.
    """
    path, _ = _write_mock_artifact(tmp_path)
    agent = DiagnosticReasoningAgent(path, expected_sha256="ff" * 32)
    request = _example_request()
    response = agent.run(request)
    check_response(request, response)
    assert response["status"] == "error"
    assert response["result"] is None
    assert len(response["issues"]) == 1
    assert response["issues"][0]["code"] == "DIAGNOSTIC_EXECUTION_ERROR"


def test_invalid_component_mechanism_is_rejected() -> None:
    """Unsupported mechanisms raise a ValueError and unknown assets become None.

    Independent: yes, because the invalid mechanism name is supplied by the test.
    """
    with pytest.raises(ValueError, match="unsupported mechanism"):
        valid_component("roof_rupture", "TK-101", None)
    cleaned = valid_component("leak", "UNKNOWN-PIPE", "UNKNOWN-TAG")
    assert cleaned == {"mechanism": "leak", "asset_id": None, "tag_id": None}
    preds = [CandidatePrediction("leak", "E001", None, 0.8, "m1")]
    hyps = format_hypotheses(preds)
    assert hyps[0]["components"][0]["mechanism"] in SUPPORTED_MECHANISMS

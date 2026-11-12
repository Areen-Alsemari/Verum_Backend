"""Tests for the Diagnostic Reasoning agent: observation inference, upstream rules and contracts.

Every test checks an explicit rule of the Diagnostic Reasoning contract, including artifact
execution on faulty windows, feature order, thresholds, ranking, support/conflict IDs and errors.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import joblib  # type: ignore[import-untyped]
import numpy as np
import pytest

from verum.agents.common import check_request, check_response, stable_hash
from verum.agents.diagnostic_reasoning import DiagnosticReasoningAgent
from verum.agents.diagnostic_reasoning import agent as agent_mod
from verum.agents.diagnostic_reasoning.features import (
    _num,
    extract_observation_vector,
    feature_names,
)
from verum.agents.diagnostic_reasoning.model import (
    DRIFT_DECISION_SCORE,
    PINNED_ARTIFACT_SHA256,
    STUCK_DECISION_SCORE,
    CandidatePrediction,
    DiagnosticModel,
    default_artifact_path,
    expected_artifact_sha256,
    format_hypotheses,
)
from verum.agents.diagnostic_reasoning.rules import (
    ASSET_PRIMARY_TAGS,
    LOW_SUPPORT_MECHANISMS,
    SUPPORTED_MECHANISMS,
    UPSTREAM_FIELDS,
    valid_component,
)
from verum.contracts.agent_interfaces import contract_directory
from verum.contracts.paths import repo_root


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


def _load_train_module() -> Any:
    script = repo_root() / "tools" / "agents" / "diagnostic_reasoning_train.py"
    spec = importlib.util.spec_from_file_location("diagnostic_reasoning_train", script)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["diagnostic_reasoning_train"] = mod
    spec.loader.exec_module(mod)
    return mod


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
    """Write a valid joblib artifact where insertion order differs from descending score order."""
    artifact = {
        "role": "diagnostic_reasoning",
        "method_id": "ovr_selected_classifier_v1",
        "feature_names": feature_names(),
        "scaler": _MockScaler(),
        "mechanism_models": {
            "pump": _MockClassifier(0.72),
            "leak": _MockClassifier(0.95),
            "drift": _MockClassifier(0.10),
        },
        "mechanism_thresholds": {"pump": 0.50, "leak": 0.50, "drift": 0.50},
        "component_models": {
            "pump::P-101A": _MockClassifier(0.78),
            "restriction_position_visible::XV-PAO": _MockClassifier(0.91),
            "bias::PT-001": _MockClassifier(0.20),
        },
        "component_thresholds": {
            "pump::P-101A": 0.50,
            "restriction_position_visible::XV-PAO": 0.50,
            "bias::PT-001": 0.50,
        },
    }
    path = tmp_path / "model_artifact.joblib"
    joblib.dump(artifact, path)
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    return path, sha


def test_diagnostic_reasoning_answers_the_example_request_validly() -> None:
    """The agent answers its standalone example request with empty hypotheses and unknown checks.

    Independent: yes, because the contract validator and literal empty state are verified.
    """
    agent = DiagnosticReasoningAgent()
    request = _example_request()
    check_request(request)
    response = agent.run(request)
    check_response(request, response)
    assert response["agent"] == "diagnostic_reasoning"
    assert response["advisory_only"] is True
    assert response["result"]["hypotheses"] == []
    assert response["result"]["assessment"] == "inconclusive"
    assert response["result"]["ranking_basis"] is None
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


def test_feature_extractor_order_missing_flags_and_derived_channels_are_exact() -> None:
    """Extracted features preserve order, missing-value flags, quality codes, and derived channels.

    Independent: yes, because specific indices, missing flags and arithmetic are checked.
    """
    assert _num(None) == (0.0, 0.0)
    assert _num(True) == (0.0, 0.0)
    assert _num(4.5) == (4.5, 1.0)
    request = _example_request()
    vec = extract_observation_vector(request["input"]["observations"])
    names = feature_names()
    assert vec.shape == (len(names),)
    assert names[0] == "FT-001__latest_value"
    assert vec[names.index("FT-001__latest_value_present")] == 1.0
    assert vec[names.index("FT-001__missing_samples")] == 1.0
    assert vec[names.index("FT-001__missing_samples_present")] == 1.0
    assert vec[names.index("FT-001__latest_is_measured")] == 1.0
    assert vec[names.index("FT-001__age_lower_bound")] == 0.0
    assert vec[names.index("LSHH-101__mean")] == 0.0
    assert vec[names.index("LSHH-101__mean_present")] == 0.0
    assert names[-5] == "derived__flow_imbalance_m3h"
    ft001_mean = vec[names.index("FT-001__mean")]
    ft201_mean = vec[names.index("FT-201__mean")]
    assert np.isclose(vec[-5], ft001_mean - ft201_mean)


def test_authoritative_pinned_hash_rejects_tampered_file_and_forged_report(
    tmp_path: Path,
) -> None:
    """PINNED_ARTIFACT_SHA256 is authoritative and ignores any forged evaluation report.

    Independent: yes, because a forged report with the mock file's hash is written next to it.
    """
    assert (
        PINNED_ARTIFACT_SHA256 == "b165dc823fc9d2c040a133cf9d922e7f563a446d962f66e8ebff7b9175d45aee"
    )
    path, mock_sha = _write_mock_artifact(tmp_path)
    forged_report = tmp_path / "evaluation_report.json"
    forged_report.write_text(json.dumps({"artifact_sha256": mock_sha}), encoding="utf-8")
    assert expected_artifact_sha256(path) == PINNED_ARTIFACT_SHA256
    with pytest.raises(ValueError, match="artifact sha256 mismatch"):
        DiagnosticModel(path)
    with pytest.raises(ValueError, match="artifact sha256 mismatch"):
        DiagnosticModel(path, expected_sha256="00" * 32)


def test_missing_artifact_returns_degraded_with_named_issue(tmp_path: Path) -> None:
    """When the artifact file is missing, run() returns degraded status with MODEL_ARTIFACT_MISSING.

    Independent: yes, because a non-existent path inside tmp_path is supplied.
    """
    missing_path = tmp_path / "missing_artifact.joblib"
    agent = DiagnosticReasoningAgent(missing_path)
    request = _example_request()
    response = agent.run(request)
    check_response(request, response)
    assert response["status"] == "degraded"
    assert response["result"]["hypotheses"] == []
    codes = [i["code"] for i in response["issues"]]
    assert "MODEL_ARTIFACT_MISSING" in codes


def test_artifact_executes_thresholds_ranking_and_low_support_markers(
    tmp_path: Path,
) -> None:
    """Artifact ranks descending across components/mechanisms and marks only low-support labels.

    Independent: yes, because mock probabilities out of alphabetical order are controlled.
    """
    raw = format_hypotheses([CandidatePrediction("leak", None, None, 0.95, "m1")])
    assert raw[0]["unresolved_questions"] == []

    path, sha = _write_mock_artifact(tmp_path)
    agent = DiagnosticReasoningAgent(path, expected_sha256=sha)
    request = _example_request()
    response = agent.run(request)
    check_response(request, response)
    hyps = response["result"]["hypotheses"]
    assert len(hyps) == 3
    assert response["result"]["assessment"] == "candidates_available"
    assert response["result"]["ranking_basis"] == "decision_score_descending"
    assert [h["score"]["value"] for h in hyps] == [0.95, 0.91, 0.78]

    assert hyps[0]["components"][0] == {"mechanism": "leak", "asset_id": None, "tag_id": None}
    assert hyps[0]["score"]["method_id"].endswith("_low_support_uncalibrated")
    leak_q = " ".join(hyps[0]["unresolved_questions"])
    assert "0.0804" in leak_q
    assert "0 of 8 eligible windows" in leak_q
    assert "2 of 69 across all records" in leak_q
    assert "as a probability" in leak_q

    assert hyps[1]["components"][0] == {
        "mechanism": "restriction_position_visible",
        "asset_id": "XV-PAO",
        "tag_id": None,
    }
    assert hyps[1]["score"]["method_id"] == "ovr_selected_classifier_v1"
    for marker in LOW_SUPPORT_MECHANISMS.values():
        assert marker not in hyps[1]["unresolved_questions"]

    assert hyps[2]["components"][0] == {
        "mechanism": "pump",
        "asset_id": "P-101A",
        "tag_id": None,
    }
    assert hyps[2]["score"]["method_id"] == "ovr_selected_classifier_v1"
    for marker in LOW_SUPPORT_MECHANISMS.values():
        assert marker not in hyps[2]["unresolved_questions"]


def test_heuristic_stuck_and_drift_scores_and_sample_thresholds(tmp_path: Path) -> None:
    """Heuristic fallback produces exact 0.75 stuck and 0.70 drift scores and respects min samples.

    Independent: yes, because synthetic signal statistics are set directly around the thresholds.
    """
    assert STUCK_DECISION_SCORE == 0.75
    assert DRIFT_DECISION_SCORE == 0.70
    model = DiagnosticModel(tmp_path / "no_artifact.joblib")
    request = _example_request()
    obs = request["input"]["observations"]
    assert model.predict_candidates(obs) == []

    for sig in obs["summary"]["signals"]:
        if sig["tag_id"] == "FT-001":
            sig["standard_deviation"] = 0.0
            sig["mean"] = 500.0
            sig["measured_count"] = 49
        elif sig["tag_id"] == "FT-201":
            sig["mean"] = 0.0
        elif sig["tag_id"] == "LT-101":
            sig["slope_per_s"] = 0.001
    assert model.predict_candidates(obs) == []

    for sig in obs["summary"]["signals"]:
        if sig["tag_id"] == "FT-001":
            sig["measured_count"] = 50
            sig["mean"] = 2.0
    preds = model.predict_candidates(obs)
    assert len(preds) == 2
    assert preds[0].mechanism == "stuck"
    assert preds[0].score == 0.75
    assert preds[1].mechanism == "drift"
    assert preds[1].score == 0.70


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
    stuck_hyps = [h for h in hyps if h["components"][0]["mechanism"] == "stuck"]
    assert len(stuck_hyps) == 1
    assert stuck_hyps[0]["score"]["value"] == 0.75


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
    anom["result"]["window_assessment"] = _pump_assessment("exceeded")
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


def _pump_assessment(r2_state: str, complete: bool = True) -> dict[str, Any]:
    """A window assessment in which only the pump head residual has the given state."""
    ids = ["R1_mass_balance", "R2_pump_head", "R3_discharge_loss", "R4_receipt_line"]
    rows = [
        {"residual_id": i, "state": r2_state if i == ids[1] else "within_normal", "reason": None}
        for i in ids
    ]
    return {
        "score": 1.0, "window_threshold": 3.0, "exceeded": False, "complete": complete,
        "persistence_rule": {"k": 2, "n": 3, "threshold": 1.5}, "residuals": rows,
    }  # fmt: skip


def _set_forecast_value(
    request: dict[str, Any], tag_id: str, unit: str, value: float | None
) -> dict[str, Any]:
    """Build a non-stub forecast_report on a copy of request with one tag forecast value."""
    req = copy.deepcopy(request)
    fc = copy.deepcopy(req["input"]["forecast_report"])
    fc["issues"] = []
    fc["status"] = "complete"
    fc["result"]["forecasts"] = [
        {
            "tag_id": tag_id,
            "quantity": "reported_mean",
            "horizon_s": 300.0,
            "value": value,
            "interval": None,
            "unit": unit,
            "evidence_ids": ["source-observations"],
            "limitations": ["Test forecast."],
        }
    ]
    req["input"]["forecast_report"] = fc
    for row in req["evidence"]:
        if row["evidence_id"] == fc["report_id"]:
            row["content_sha256"] = stable_hash(fc)
    return req


def test_forecast_report_check_compares_direction_and_stuck_returns_unknown(
    tmp_path: Path,
) -> None:
    """Forecast check returns unknown on flat/stuck overlap, pass on agreement, fail on conflict.

    Independent: yes, because neutral, dropping, rising and stuck forecast values are supplied.
    """
    path, sha = _write_mock_artifact(tmp_path)
    agent = DiagnosticReasoningAgent(path, expected_sha256=sha)
    base_req = _chained_request()

    neutral_req = _set_forecast_value(base_req, "PT-202A", "barg", 2.0001)
    neutral_res = agent.run(neutral_req)
    check_response(neutral_req, neutral_res)
    fc_id = neutral_req["input"]["forecast_report"]["report_id"]
    fc_check = next(
        c for c in neutral_res["result"]["upstream_checks"] if c["check_id"] == "forecast_report"
    )
    pump_hyp = next(
        h for h in neutral_res["result"]["hypotheses"] if h["components"][0]["asset_id"] == "P-101A"
    )
    assert fc_check["outcome"] == "unknown"
    assert fc_id not in pump_hyp["support_evidence_ids"]
    assert fc_id not in pump_hyp["conflict_evidence_ids"]

    agree_req = _set_forecast_value(base_req, "PT-202A", "barg", 1.50)
    agree_res = agent.run(agree_req)
    check_response(agree_req, agree_res)
    fc_check_agree = next(
        c for c in agree_res["result"]["upstream_checks"] if c["check_id"] == "forecast_report"
    )
    pump_agree = next(
        h for h in agree_res["result"]["hypotheses"] if h["components"][0]["asset_id"] == "P-101A"
    )
    assert fc_check_agree["outcome"] == "pass"
    assert fc_id in pump_agree["support_evidence_ids"]

    conflict_req = _set_forecast_value(base_req, "PT-202A", "barg", 2.60)
    conflict_res = agent.run(conflict_req)
    check_response(conflict_req, conflict_res)
    fc_check_conflict = next(
        c for c in conflict_res["result"]["upstream_checks"] if c["check_id"] == "forecast_report"
    )
    pump_conflict = next(
        h
        for h in conflict_res["result"]["hypotheses"]
        if h["components"][0]["asset_id"] == "P-101A"
    )
    assert fc_check_conflict["outcome"] == "fail"
    assert fc_id in pump_conflict["conflict_evidence_ids"]

    stuck_agent = DiagnosticReasoningAgent(tmp_path / "no_artifact.joblib")
    stuck_base = _chained_request()
    for sig in stuck_base["input"]["observations"]["summary"]["signals"]:
        if sig["tag_id"] == "FT-001":
            sig["standard_deviation"] = 0.0
            sig["mean"] = 500.0
            sig["latest_value"] = 500.0
            sig["measured_count"] = 300
            sig["missing_samples"] = 0
    for row in stuck_base["evidence"]:
        if row["evidence_id"] == "features-summary":
            row["content_sha256"] = stable_hash(stuck_base["input"]["observations"]["summary"])
    stuck_same = _set_forecast_value(stuck_base, "FT-001", "m3/h", 500.0)
    stuck_same_res = stuck_agent.run(stuck_same)
    check_response(stuck_same, stuck_same_res)
    stuck_fc_check = next(
        c for c in stuck_same_res["result"]["upstream_checks"] if c["check_id"] == "forecast_report"
    )
    assert stuck_fc_check["outcome"] == "unknown"
    assert fc_id not in stuck_same_res["result"]["hypotheses"][0]["support_evidence_ids"]


def test_runtime_and_helper_exceptions_in_run_return_error_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Internal model and envelope helper errors inside run() are caught and return status error.

    Independent: yes, because broken hashes and monkeypatched helpers force exceptions directly.
    """
    path, sha = _write_mock_artifact(tmp_path)
    broken_agent = DiagnosticReasoningAgent(path, expected_sha256="ff" * 32)
    request = _example_request()
    response = broken_agent.run(request)
    check_response(request, response)
    assert response["status"] == "error"
    assert response["result"] is None
    assert response["issues"][0]["code"] == "DIAGNOSTIC_EXECUTION_ERROR"

    good_agent = DiagnosticReasoningAgent(path, expected_sha256=sha)
    for helper_name in ("_consumed_ids", "make_issue", "build_response", "check_response"):
        with monkeypatch.context() as mp:
            mp.setattr(
                agent_mod,
                helper_name,
                lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("helper failed")),
            )
            err_res = good_agent.run(request)
            assert err_res["status"] == "error"
            assert err_res["result"] is None
            assert err_res["issues"][0]["code"] == "DIAGNOSTIC_EXECUTION_ERROR"


def test_training_split_loss_mask_and_eval_only_package_write_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_load_split filters by supervised_loss_mask and --eval-only refuses package folder writes.

    Independent: yes, because synthetic records with True/False masks and package paths are passed.
    """
    train_mod = _load_train_module()
    obs = _example_request()["input"]["observations"]
    rec_elig = SimpleNamespace(
        example_id="ex-1",
        input={"observations": obs},
        target={
            "supervised_loss_mask": True,
            "injected_components": [
                {"mechanism": "pump", "asset_id": "P-101A"},
                {"mechanism": "bias", "asset_id": "FT-001"},
            ],
        },
    )
    rec_inelig = SimpleNamespace(
        example_id="ex-2",
        input={"observations": obs},
        target={
            "supervised_loss_mask": False,
            "injected_components": [{"mechanism": "leak", "asset_id": "E001"}],
        },
    )
    monkeypatch.setattr(train_mod, "episode_lookup", lambda rel, sp: {})
    monkeypatch.setattr(
        train_mod, "iter_role_records", lambda rel, role, sp: [rec_elig, rec_inelig]
    )
    x_mat, y_mech, y_comp, eps, raw_s, inelig_s, inelig_leak = train_mod._load_split(
        tmp_path, "test"
    )
    assert x_mat.shape[0] == 1
    assert int(y_mech["pump"][0]) == 1
    assert int(y_mech["leak"][0]) == 0
    assert "pump::P-101A" in y_comp
    assert "bias::FT-001" not in y_comp
    assert len(inelig_s) == 1
    assert int(inelig_leak[0]) == 1

    pkg_report = default_artifact_path().with_name("evaluation_report.json")
    with pytest.raises(ValueError, match="refuses to write into the package folder"):
        train_mod.evaluate_existing_artifact(
            tmp_path, default_artifact_path(), report_out=pkg_report
        )


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


NO_TARGET_TEXT = "names no tag or asset"


def _anomaly_event(tag_ids: list[str], asset_ids: list[str], category: str) -> dict[str, Any]:
    """One anomaly event with the given tag and asset lists."""
    return {
        "event_id": "EV-" + category,
        "tag_ids": tag_ids,
        "asset_ids": asset_ids,
        "category": category,
        "score": None,
        "method_id": "rule_v1",
        "evidence_ids": ["source-observations"],
        "limitations": ["Rule check."],
    }


def _model_event() -> dict[str, Any]:
    """The detector's window-level event, which names no tag and no asset."""
    return _anomaly_event([], [], "reported_signal_departure")


def _run_with_events(
    tmp_path: Path, events: list[dict[str, Any]], assessment: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Run the agent on the chained request with a usable anomaly report holding these events."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    path, sha = _write_mock_artifact(tmp_path)
    request = _chained_request()
    anom = copy.deepcopy(request["input"]["anomaly_report"])
    anom.update(issues=[], status="complete")
    anom["result"].update(coverage="assessed", events=events)
    if assessment is not None:
        anom["result"]["window_assessment"] = assessment
    request["input"]["anomaly_report"] = anom
    for row in request["evidence"]:
        if row["evidence_id"] == anom["report_id"]:
            row["content_sha256"] = stable_hash(anom)
    response: dict[str, Any] = DiagnosticReasoningAgent(path, expected_sha256=sha).run(request)
    check_response(request, response)
    response["_anomaly_id"] = anom["report_id"]
    return response


def _pump(response: dict[str, Any]) -> dict[str, Any]:
    hyp: dict[str, Any] = next(
        h for h in response["result"]["hypotheses"] if h["components"][0]["asset_id"] == "P-101A"
    )
    return hyp


def test_event_naming_no_tag_or_asset_is_neither_support_nor_conflict(tmp_path: Path) -> None:
    """A tag-less, asset-less event adds no support or conflict, an unknown check and a message.

    Independent: yes, because the event and its empty lists are built by the test.
    """
    response = _run_with_events(tmp_path, [_model_event()])
    anomaly_id = response["_anomaly_id"]
    assert len(response["result"]["hypotheses"]) >= 2
    for hyp in response["result"]["hypotheses"]:
        assert anomaly_id not in hyp["support_evidence_ids"]
        assert anomaly_id not in hyp["conflict_evidence_ids"]
        assert any(NO_TARGET_TEXT in q for q in hyp["unresolved_questions"])
    check = next(
        c for c in response["result"]["upstream_checks"] if c["check_id"] == "anomaly_report"
    )
    assert check["outcome"] == "unknown"
    assert NO_TARGET_TEXT in check["description"]
    assert check["evidence_ids"] == [anomaly_id]


def test_event_naming_the_candidate_asset_no_longer_supports(tmp_path: Path) -> None:
    """An event that names the candidate's asset is not support; only the assessment decides.

    Independent: yes, because the event names the asset of the mock pump candidate and the
    report holds no window assessment.
    """
    response = _run_with_events(
        tmp_path, [_model_event(), _anomaly_event([], ["P-101A"], "non_good_quality")]
    )
    pump = _pump(response)
    assert response["_anomaly_id"] not in pump["support_evidence_ids"]
    assert response["_anomaly_id"] not in pump["conflict_evidence_ids"]
    assert any("no usable window assessment" in q for q in pump["unresolved_questions"])
    check = next(
        c for c in response["result"]["upstream_checks"] if c["check_id"] == "anomaly_report"
    )
    assert check["outcome"] == "unknown"


def test_event_naming_another_asset_is_no_longer_a_conflict(tmp_path: Path) -> None:
    """An event that names only other tags and assets is not a conflict either.

    Independent: yes, because the event names a tank tag and valve that the pump does not use.
    """
    response = _run_with_events(
        tmp_path, [_anomaly_event(["TT-103"], ["XV-S103"], "non_good_quality")]
    )
    pump = _pump(response)
    assert response["_anomaly_id"] not in pump["conflict_evidence_ids"]
    assert response["_anomaly_id"] not in pump["support_evidence_ids"]
    assert not any(NO_TARGET_TEXT in q for q in pump["unresolved_questions"])


def test_the_window_assessment_decides_and_tagged_quality_events_do_not(tmp_path: Path) -> None:
    """With a window assessment the pump residual decides; quality events change nothing.

    Independent: yes, because the tags are taken from the pump's declared primary tags and the
    assessment is built by the test.
    """
    on_pump = ASSET_PRIMARY_TAGS["P-101A"][1]
    overlapping = _anomaly_event([on_pump], [], "missing_reading")
    elsewhere = _anomaly_event(["TT-103"], [], "missing_reading")
    loud = _run_with_events(tmp_path, [_model_event(), elsewhere], _pump_assessment("exceeded"))
    assert loud["_anomaly_id"] in _pump(loud)["support_evidence_ids"]
    assert loud["_anomaly_id"] not in _pump(loud)["conflict_evidence_ids"]
    quiet = _run_with_events(tmp_path / "quiet", [elsewhere], _pump_assessment("within_normal"))
    assert quiet["_anomaly_id"] in _pump(quiet)["conflict_evidence_ids"]
    caveat = _run_with_events(tmp_path / "caveat", [overlapping], _pump_assessment("within_normal"))
    assert caveat["_anomaly_id"] not in _pump(caveat)["conflict_evidence_ids"]
    assert any("Data-quality caveat" in q for q in _pump(caveat)["unresolved_questions"])


def test_anomaly_event_shape_does_not_change_the_hypotheses(tmp_path: Path) -> None:
    """Hypothesis ids, components and scores are the same whatever the anomaly events say.

    Independent: yes, because only the events change and the mock model scores are fixed.
    """
    shapes = [
        [],
        [_model_event()],
        [_anomaly_event([], ["P-101A"], "non_good_quality")],
        [_anomaly_event(["TT-103"], ["XV-S103"], "non_good_quality")],
    ]
    seen = []
    for index, events in enumerate(shapes):
        response = _run_with_events(tmp_path / str(index), events)
        seen.append(
            [
                (h["hypothesis_id"], h["components"], h["score"])
                for h in response["result"]["hypotheses"]
            ]
        )
    assert seen[0] and all(item == seen[0] for item in seen)

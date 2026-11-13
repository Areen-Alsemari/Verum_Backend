"""Tests of the candidates that Agent 5 raises from the residual pattern of the anomaly report."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import joblib  # type: ignore[import-untyped]
import numpy as np
import pytest

from verum.agents.common import check_response, stable_hash
from verum.agents.diagnostic_reasoning import DiagnosticReasoningAgent
from verum.agents.diagnostic_reasoning import agent as agent_mod
from verum.agents.diagnostic_reasoning.candidates import (
    CANDIDATE_RANKING,
    PERSISTENCE_NOTE,
    UNLOCALISED_NOTE,
    residual_candidates,
)
from verum.agents.diagnostic_reasoning.features import feature_names
from verum.agents.diagnostic_reasoning.mechanism import NO_FAMILY
from verum.agents.diagnostic_reasoning.rules import LOW_SUPPORT_MECHANISMS

pytestmark = pytest.mark.fast
IDS = {"R1": "R1_mass_balance", "R2": "R2_pump_head", "R3": "R3_discharge_loss",
       "R4": "R4_receipt_line"}  # fmt: skip
READS = {
    "R1": ["FT-001", "FT-201", "LT-101", "LT-102", "LT-103"],
    "R2": ["FT-201", "PT-202A", "PT-201", "P-101A"],
    "R3": ["FT-201", "PT-202A", "PT-203", "P-101A"],
    "R4": ["FT-001", "PT-001"],
}
REPORT_ID = "anomaly-report-1"
CHAINED = Path(__file__).resolve().parents[1] / "fixtures" / "chained"


def assessment(exceeded: set[str], window_exceeded: bool = True) -> dict[str, Any]:
    """A complete window assessment with the given residuals exceeded."""
    rows = [
        {"residual_id": rid, "state": "exceeded" if key in exceeded else "within_normal",
         "reason": None}
        for key, rid in IDS.items()
    ]  # fmt: skip
    return {
        "score": 4.0 if window_exceeded else 2.0, "window_threshold": 3.0,
        "exceeded": window_exceeded, "complete": True,
        "persistence_rule": {"k": 2, "n": 3, "threshold": 1.7}, "residuals": rows,
    }  # fmt: skip


def residual_event(key: str) -> dict[str, Any]:
    """The Agent 2 event of one exceeded residual, naming the tags it reads."""
    return {
        "event_id": f"req-residual-{key}", "tag_ids": READS[key], "asset_ids": [],
        "category": "reported_signal_departure", "score": None, "method_id": "m",
        "evidence_ids": ["source-observations"], "limitations": ["x"],
    }  # fmt: skip


def report(exceeded: set[str], window_exceeded: bool = True) -> dict[str, Any]:
    """A complete anomaly report with the assessment and one event per exceeded residual."""
    return {
        "report_id": REPORT_ID, "status": "complete", "issues": [],
        "result": {
            "events": [residual_event(k) for k in sorted(exceeded)], "coverage": "assessed",
            "window_assessment": assessment(exceeded, window_exceeded),
        },
    }  # fmt: skip


def candidates(
    exceeded: set[str], alarming: bool | None = None, window_exceeded: bool = True
) -> list[dict[str, Any]]:
    """Candidates for a request holding only this anomaly report and persistence statement."""
    inputs: dict[str, Any] = {"anomaly_report": report(exceeded, window_exceeded)}
    inputs["persistence"] = {"rule": None, "windows_held": 3, "windows_exceeding": 2,
                             "windows_unknown": 0, "alarming": alarming}  # fmt: skip
    return residual_candidates(inputs, ["obs"])


def targets(found: list[dict[str, Any]]) -> list[tuple[str, str | None, str | None]]:
    """Mechanism, asset and tag of each candidate, in order."""
    return [
        (c["components"][0]["mechanism"], c["components"][0]["asset_id"],
         c["components"][0]["tag_id"])
        for c in found
    ]  # fmt: skip


def test_r2_alone_gives_the_pump_the_inlet_valves_and_the_suction_transmitter() -> None:
    """R2 maps back to the families whose expected set is R2, in the order of the table.

    Independent: yes, because the expected sets are written in the mechanism module from the
    layout and the event names pump A, which the test chose.
    """
    found = candidates({"R2"})
    assert targets(found) == [
        ("pump", "P-101A", None),
        ("restriction_position_visible", None, None),
        ("drift", "PT-201", "PT-201"),
    ]
    assert "pump inlet valve" in found[1]["unresolved_questions"][0]
    assert UNLOCALISED_NOTE in found[1]["unresolved_questions"]


def test_r2_and_r3_put_the_running_pump_discharge_transmitter_first() -> None:
    """The family that explains both residuals comes first; only the running pump's one is named.

    Independent: yes, because the event of R2 and R3 names PT-202A and not PT-202B.
    """
    found = targets(candidates({"R2", "R3"}))
    assert found[0] == ("drift", "PT-202A", "PT-202A")
    assert all(tag != "PT-202B" for _, _, tag in found)
    assert ("drift", "PT-203", "PT-203") in found and ("pump", "P-101A", None) in found


def test_r1_gives_family_level_leak_and_sensor_candidates() -> None:
    """R1 names both flow meters and all level transmitters, so nothing is localised.

    Independent: yes, because the mass balance reads five tags by the layout.
    """
    found = candidates({"R1"})
    assert targets(found) == [("leak", None, None), ("drift", None, None), ("drift", None, None)]
    for hyp in found:
        assert hyp["score"] is None
        assert REPORT_ID in hyp["support_evidence_ids"]
        assert NO_FAMILY not in hyp["unresolved_questions"]
        assert LOW_SUPPORT_MECHANISMS["leak"] not in hyp["unresolved_questions"]


def test_r4_gives_the_receipt_valves_and_the_receipt_transmitter() -> None:
    """R4 maps back to the receipt-side restriction and to PT-001.

    Independent: yes, because the receipt residual reads FT-001 and PT-001 only.
    """
    assert targets(candidates({"R4"})) == [
        ("restriction_position_visible", None, None),
        ("drift", "PT-001", "PT-001"),
    ]


def test_a_window_below_its_threshold_or_a_known_quiet_run_gives_no_candidate() -> None:
    """The window flag must be raised and persistence must not be known to be false.

    Independent: yes, because both flags are set by the test.
    """
    assert candidates({"R2"}, window_exceeded=False) == []
    assert candidates({"R2"}, alarming=False) == []
    assert candidates(set()) == []


def test_unknown_persistence_is_stated_and_known_persistence_is_not() -> None:
    """A candidate says when persistence is unknown and does not when it is known.

    Independent: yes, because the persistence statement is set by the test.
    """
    assert PERSISTENCE_NOTE in candidates({"R4"}, alarming=None)[0]["unresolved_questions"]
    assert PERSISTENCE_NOTE not in candidates({"R4"}, alarming=True)[0]["unresolved_questions"]


def test_no_report_or_no_assessment_gives_no_candidate() -> None:
    """Without an anomaly report or its window assessment there is nothing to read back.

    Independent: yes, because the reports are built by the test.
    """
    stripped = report({"R2"})
    del stripped["result"]["window_assessment"]
    assert residual_candidates({"anomaly_report": None}, []) == []
    assert residual_candidates({"anomaly_report": stripped}, []) == []


class _Scaler:
    def transform(self, x: np.ndarray) -> np.ndarray:
        return x


class _Fixed:
    def __init__(self, prob: float) -> None:
        self.prob = prob

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        return np.asarray([[1.0 - self.prob, self.prob]], dtype=np.float64)


def artifact(tmp_path: Path, prob: float) -> DiagnosticReasoningAgent:
    """An agent whose single classifier gives the same probability for every window."""
    content = {
        "role": "diagnostic_reasoning", "method_id": "ovr_selected_classifier_v1",
        "feature_names": feature_names(), "scaler": _Scaler(),
        "mechanism_models": {"pump": _Fixed(prob)}, "mechanism_thresholds": {"pump": 0.5},
        "component_models": {"pump::P-101A": _Fixed(prob)},
        "component_thresholds": {"pump::P-101A": 0.5},
    }  # fmt: skip
    path = tmp_path / f"artifact_{prob}.joblib"
    joblib.dump(content, path)
    return DiagnosticReasoningAgent(path, hashlib.sha256(path.read_bytes()).hexdigest())


def request_with(window: dict[str, Any] | None) -> dict[str, Any]:
    """The chained Agent 5 request with an R2 event and the given window assessment."""
    path = CHAINED / "diagnostic_reasoning.request.json"
    request: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    anom = copy.deepcopy(request["input"]["anomaly_report"])
    anom.update(issues=[], status="complete")
    anom["result"].update(coverage="assessed", events=[residual_event("R2")])
    anom["result"].pop("window_assessment", None)
    if window is not None:
        anom["result"]["window_assessment"] = window
    request["input"]["anomaly_report"] = anom
    for row in request["evidence"]:
        if row["evidence_id"] == anom["report_id"]:
            row["content_sha256"] = stable_hash(anom)
    return request


def without_candidates(
    agent: DiagnosticReasoningAgent, request: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    """The response of the agent with the candidate step switched off."""
    with monkeypatch.context() as patch:
        patch.setattr(agent_mod, "residual_candidates", lambda inputs, ids: [])
        response: dict[str, Any] = agent.run(request)
    return response


def test_the_agent_adds_valid_candidates_only_when_the_classifier_has_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A quiet classifier and an alarming window give contract-valid candidates without a score.

    Independent: yes, because the classifier probability and the assessment are set by the test.
    """
    request = request_with(assessment({"R2"}))
    response = artifact(tmp_path, 0.1).run(request)
    check_response(request, response)
    result = response["result"]
    hyps = result["hypotheses"]
    assert hyps and all(h["hypothesis_id"].startswith("HYP-A2-") for h in hyps)
    assert all(h["score"] is None for h in hyps)
    assert result["ranking_basis"] == CANDIDATE_RANKING
    assert result["assessment"] == "candidates_available"
    check = next(c for c in result["upstream_checks"] if c["check_id"] == "anomaly_report")
    assert check["outcome"] == "pass"


def test_existing_hypotheses_are_unchanged_by_an_alarming_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With a classifier hypothesis the response is the same with the candidate step on or off.

    Independent: yes, because the reference response comes from the agent with the step removed.
    """
    agent = artifact(tmp_path, 0.9)
    request = request_with(assessment({"R2"}))
    assert agent.run(request) == without_candidates(agent, request, monkeypatch)
    assert agent.run(request)["result"]["hypotheses"][0]["hypothesis_id"].startswith("HYP-01-")


@pytest.mark.parametrize(
    "window", [None, assessment({"R2"}, window_exceeded=False)], ids=["absent", "below"]
)
def test_absent_or_quiet_assessment_gives_the_previous_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, window: dict[str, Any] | None
) -> None:
    """Without an alarming assessment the response equals the response without the step.

    Independent: yes, because the reference response comes from the agent with the step removed.
    """
    agent = artifact(tmp_path, 0.1)
    request = request_with(window)
    response = agent.run(request)
    assert response == without_candidates(agent, request, monkeypatch)
    assert response["result"]["hypotheses"] == []

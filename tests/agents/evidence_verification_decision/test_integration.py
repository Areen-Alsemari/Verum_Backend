"""Integration tests for Agent 8 using registered upstream reports."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from verum.agents.common import EvidenceRegistry, check_request, check_response
from verum.agents.common.numbers import stable_hash
from verum.agents.evidence_verification_decision import (
    EvidenceVerificationDecisionAgent,
)

EXAMPLES = Path(__file__).resolve().parents[3] / "contracts/agents/v1/examples"
ROLES = (
    ("diagnostic_reasoning", "diagnosis_report"),
    ("inspection_planning", "inspection_plan_report"),
    ("inspection_quality_documentation", "inspection_quality_report"),
)


def _load(filename: str) -> dict[str, Any]:
    """Load a version-controlled contract example."""
    result: dict[str, Any] = json.loads((EXAMPLES / filename).read_text(encoding="utf-8"))
    return result


def _request_with_reports() -> dict[str, Any]:
    """Build an Agent 8 request with registered upstream reports."""
    request = _load("evidence_verification_decision.request.json")
    registry = EvidenceRegistry.from_rows(request["context"], request["evidence"])

    for role, field in ROLES:
        report = _load(f"{role}.response.json")
        request["input"][field] = registry.add_report(report)

    request["evidence"] = registry.rows()
    check_request(request)
    return request


def _run(request: dict[str, Any]) -> dict[str, Any]:
    """Run Agent 8 and independently validate its response."""
    response = EvidenceVerificationDecisionAgent().run(request)
    check_response(request, response)
    return response


def _reregister_reports(request: dict[str, Any]) -> None:
    """Refresh report evidence hashes after modifying embedded reports."""
    registry = EvidenceRegistry.from_rows(
        request["context"],
        [row for row in request["evidence"] if row["kind"] != "agent_report"],
    )

    for _, field in ROLES:
        report = request["input"][field]
        if report is not None:
            registry.add_report(report)

    request["evidence"] = registry.rows()


def _registered_request_with_changes(
    *,
    diagnosis_candidates: bool = False,
    quality_usable: bool = False,
) -> dict[str, Any]:
    """Build a request with modified, correctly registered reports."""
    request = _request_with_reports()

    if diagnosis_candidates:
        diagnosis = request["input"]["diagnosis_report"]
        diagnosis["result"]["assessment"] = "candidates_available"
        diagnosis["result"]["hypotheses"] = [
            {
                "hypothesis_id": "hypothesis-1",
                "components": [
                    {
                        "mechanism": "leak",
                        "asset_id": None,
                        "tag_id": None,
                    }
                ],
                "score": None,
                "support_evidence_ids": ["source-observations"],
                "conflict_evidence_ids": [],
                "unresolved_questions": [],
            }
        ]

    if quality_usable:
        quality = request["input"]["inspection_quality_report"]
        quality["result"]["record_checks"] = [
            {
                "result_id": "inspection-result-1",
                "checks": [],
                "measurement_usable": True,
                "scope_supported": True,
                "equipment_condition_confirmed": False,
                "evidence_ids": ["source-observations"],
            }
        ]

    _reregister_reports(request)
    check_request(request)
    return request


def _verified_proposal(proposal_id: str) -> dict[str, Any]:
    """Return a proposal referencing an existing observation source."""
    return {
        "proposal_id": proposal_id,
        "source_ref": "observations:training-prefix-at-300",
        "claimed_available_at_s": 300.0,
        "claimed_evidence_ids": ["source-observations"],
    }


def test_real_contract_reports_require_more_evidence() -> None:
    """Independent: reports without verified evidence require more evidence."""
    response = _run(_request_with_reports())
    result = response["result"]

    assert result["decision_state"] == "more_evidence_required"
    assert result["hypothesis_report_ids"] == []
    assert result["human_decision_required"] is True
    assert result["automatic_action_authorized"] is False
    assert result["equipment_condition_confirmed"] is False
    assert response["advisory_only"] is True


def test_all_attached_reports_are_consumed() -> None:
    """Independent: Report provenance must appear in consumed evidence IDs."""
    request = _request_with_reports()
    response = _run(request)

    expected = {request["input"][field]["report_id"] for _, field in ROLES}

    assert expected <= set(response["consumed_evidence_ids"])


def test_registered_report_hash_matches_content() -> None:
    """Independent: Registry hashes must match the complete report content."""
    request = _request_with_reports()
    registry = {row["evidence_id"]: row for row in request["evidence"]}

    for _, field in ROLES:
        report = request["input"][field]
        row = registry[report["report_id"]]

        assert row["kind"] == "agent_report"
        assert row["content_sha256"] == stable_hash(report)
        assert row["source_ref"] == "report:" + report["report_id"]


def test_report_context_mismatch_is_rejected() -> None:
    """Independent: A report from another snapshot must be rejected."""
    request = _request_with_reports()
    request["input"]["diagnosis_report"]["context"]["revision"] += 1

    with pytest.raises(ValueError):
        check_request(request)


def test_report_hash_tampering_is_rejected() -> None:
    """Independent: Modified report content must invalidate its registry hash."""
    request = _request_with_reports()
    request["input"]["diagnosis_report"]["limitations"].append("Tampered after registration")

    with pytest.raises(ValueError):
        check_request(request)


def test_report_registration_is_deterministic() -> None:
    """Independent: Identical reports must generate identical registry records."""
    first = _request_with_reports()
    second = _request_with_reports()

    assert first == second
    assert _run(first) == _run(second)


def test_failed_diagnostic_check_is_reported_as_conflict() -> None:
    """Independent: Failed upstream diagnostic checks must create conflicts."""
    request = _request_with_reports()
    diagnosis = request["input"]["diagnosis_report"]

    diagnosis["result"]["upstream_checks"][0]["outcome"] = "fail"

    _reregister_reports(request)

    response = _run(request)

    assert any(row["outcome"] == "fail" for row in response["result"]["conflicts"])


def test_hypothesis_conflict_evidence_is_reported() -> None:
    """Independent: hypothesis conflict evidence remains visible."""
    request = _registered_request_with_changes(diagnosis_candidates=True)
    hypothesis = request["input"]["diagnosis_report"]["result"]["hypotheses"][0]
    hypothesis["conflict_evidence_ids"] = ["source-observations"]
    _reregister_reports(request)

    response = _run(request)

    assert any(
        row["check_id"] == "diagnosis:hypothesis:hypothesis-1"
        and "source-observations" in row["evidence_ids"]
        for row in response["result"]["conflicts"]
    )


def test_missing_quality_report_requires_more_evidence() -> None:
    """Independent: Missing inspection quality must not be silently accepted."""
    request = _request_with_reports()
    request["input"]["inspection_quality_report"] = None

    response = _run(request)

    assert response["result"]["decision_state"] == "more_evidence_required"


def test_all_decisions_remain_advisory() -> None:
    """Independent: Upstream reports must never authorize equipment actions."""
    request = _request_with_reports()
    original = copy.deepcopy(request)

    response = _run(request)
    result = response["result"]

    assert result["human_decision_required"] is True
    assert result["automatic_action_authorized"] is False
    assert result["equipment_condition_confirmed"] is False
    assert request == original


def test_empty_proposals_cannot_make_assessment_available() -> None:
    """Independent: empty proposals and quality checks require evidence."""
    request = _registered_request_with_changes(diagnosis_candidates=True)
    request["input"]["evidence_proposals"] = []
    request["input"]["inspection_quality_report"]["result"]["record_checks"] = []
    _reregister_reports(request)

    response = _run(request)

    assert response["result"]["evidence_checks"] == []
    assert response["result"]["decision_state"] == "more_evidence_required"


def test_shared_root_does_not_transfer_quality() -> None:
    """Independent: quality must cite the proposal evidence itself."""
    request = _registered_request_with_changes(
        diagnosis_candidates=True,
        quality_usable=True,
    )
    registry = {row["evidence_id"]: row for row in request["evidence"]}
    derived = registry["features-summary"]
    assert derived["root_evidence_ids"] == ["source-observations"]
    request["input"]["evidence_proposals"] = [
        {
            "proposal_id": "proposal-derived",
            "source_ref": derived["source_ref"],
            "claimed_available_at_s": derived["available_at_s"],
            "claimed_evidence_ids": ["features-summary"],
        }
    ]

    response = _run(request)
    check = response["result"]["evidence_checks"][0]

    assert check["quality_acceptable"] is None
    assert check["scope_supported"] is None
    assert check["usable"] is not True
    assert response["result"]["decision_state"] == "more_evidence_required"


def test_failing_quality_record_overrides_passing_record() -> None:
    """Independent: a passing quality record must not hide a failing one."""
    request = _registered_request_with_changes(
        diagnosis_candidates=True,
        quality_usable=True,
    )

    quality = request["input"]["inspection_quality_report"]
    passing = quality["result"]["record_checks"][0]
    failing = {
        **passing,
        "result_id": "inspection-result-failing",
        "measurement_usable": False,
    }
    quality["result"]["record_checks"].append(failing)

    _reregister_reports(request)
    check_request(request)

    request["input"]["evidence_proposals"] = [
        _verified_proposal("proposal-mixed-quality")
    ]

    response = _run(request)
    result = response["result"]
    check = result["evidence_checks"][0]

    assert check["quality_acceptable"] is False
    assert check["usable"] is not True
    assert result["decision_state"] == "more_evidence_required"


def test_assessment_available_with_verified_evidence() -> None:
    """Independent: Verified evidence and diagnostic candidates allow an assessment."""
    request = _registered_request_with_changes(
        diagnosis_candidates=True,
        quality_usable=True,
    )

    request["input"]["evidence_proposals"] = [_verified_proposal("proposal-verified-1")]

    response = _run(request)
    result = response["result"]

    assert result["decision_state"] == "assessment_available"
    assert result["evidence_checks"]
    assert all(check["usable"] is True for check in result["evidence_checks"])
    assert result["human_decision_required"] is True
    assert result["automatic_action_authorized"] is False
    assert result["equipment_condition_confirmed"] is False


def test_usable_proposal_with_missing_upstream_report() -> None:
    """Independent: usable proposals cannot override a missing upstream report."""
    request = _registered_request_with_changes(
        diagnosis_candidates=True,
        quality_usable=True,
    )
    request["input"]["evidence_proposals"] = [
        _verified_proposal("proposal-missing-report")
    ]

    # Remove the planning report, not the quality report, so the
    # proposal can remain usable.
    request["input"]["inspection_plan_report"] = None

    response = _run(request)
    result = response["result"]

    assert result["evidence_checks"]
    assert all(check["usable"] is True for check in result["evidence_checks"])
    assert result["decision_state"] == "more_evidence_required"
    assert result["decision_state"] != "assessment_available"


def _fail_upstream_report(request: dict[str, Any], field: str, status: str) -> None:
    """Keep an upstream report in the request but make it a resultless failure."""
    report = request["input"][field]
    report["status"] = status
    report["result"] = None
    report["issues"] = [
        {"code": "UPSTREAM_FAILED", "message": "Forced upstream failure.", "evidence_ids": []}
    ]
    _reregister_reports(request)
    check_request(request)


@pytest.mark.parametrize("field", ["inspection_plan_report", "diagnosis_report"])
@pytest.mark.parametrize("status", ["error", "insufficient_evidence"])
def test_usable_proposal_with_failed_upstream_report(field: str, status: str) -> None:
    """Independent: a present but failed upstream report still blocks an assessment."""
    request = _registered_request_with_changes(diagnosis_candidates=True, quality_usable=True)
    request["input"]["evidence_proposals"] = [_verified_proposal("proposal-failed-report")]

    control = _run(copy.deepcopy(request))
    assert control["result"]["decision_state"] == "assessment_available"

    _fail_upstream_report(request, field, status)
    response = _run(request)
    result = response["result"]

    assert result["evidence_checks"]
    assert all(check["usable"] is True for check in result["evidence_checks"])
    assert response["status"] == "degraded"
    assert result["decision_state"] == "more_evidence_required"
    assert result["human_decision_required"] is True
    assert result["automatic_action_authorized"] is False
    assert result["equipment_condition_confirmed"] is False
    assert request["input"][field]["report_id"] in response["consumed_evidence_ids"]


def test_review_required_when_verified_proposals_share_roots() -> None:
    """Independent: Overlapping evidence roots must trigger human review."""
    request = _registered_request_with_changes(
        quality_usable=True,
    )

    request["input"]["evidence_proposals"] = [
        _verified_proposal("proposal-review-1"),
        _verified_proposal("proposal-review-2"),
    ]

    response = _run(request)
    result = response["result"]

    assert result["decision_state"] == "review_required"
    assert result["conflicts"]
    assert result["human_decision_required"] is True
    assert result["automatic_action_authorized"] is False
    assert result["equipment_condition_confirmed"] is False


def test_run_returns_error_when_evidence_check_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Independent: A processing exception produces a resultless error response."""
    import verum.agents.evidence_verification_decision.agent as module

    request = _registered_request_with_changes(diagnosis_candidates=True, quality_usable=True)
    request["input"]["evidence_proposals"] = [_verified_proposal("proposal-error")]

    def forced_failure(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("forced verification failure")

    monkeypatch.setattr(module, "check_proposal", forced_failure)

    response = module.EvidenceVerificationDecisionAgent().run(request)

    assert response["status"] == "error"
    assert response["result"] is None
    assert any(issue["code"] == "EVIDENCE_DECISION_ERROR" for issue in response["issues"])
    expected = {
        request["input"][field]["report_id"]
        for field in (
            "diagnosis_report",
            "inspection_plan_report",
            "inspection_quality_report",
        )
    }
    assert expected <= set(response["consumed_evidence_ids"])
    check_response(request, response)


@pytest.mark.parametrize("failing_function", ["make_issue", "build_response"])
def test_error_handler_survives_response_helper_failure(
    monkeypatch: pytest.MonkeyPatch,
    failing_function: str,
) -> None:
    """Independent: error handling survives failures in response helpers."""
    import verum.agents.evidence_verification_decision.agent as module

    request = _registered_request_with_changes(
        diagnosis_candidates=True,
        quality_usable=True,
    )
    request["input"]["evidence_proposals"] = [
        _verified_proposal("proposal-helper-error")
    ]

    def forced_failure(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("forced helper failure")

    monkeypatch.setattr(module, "check_proposal", forced_failure)
    monkeypatch.setattr(module, failing_function, forced_failure)

    response = module.EvidenceVerificationDecisionAgent().run(request)

    assert response["status"] == "error"
    assert response["result"] is None
    expected = {
        request["input"][field]["report_id"]
        for field in (
            "diagnosis_report",
            "inspection_plan_report",
            "inspection_quality_report",
        )
    }
    assert expected <= set(response["consumed_evidence_ids"])
    check_response(request, response)

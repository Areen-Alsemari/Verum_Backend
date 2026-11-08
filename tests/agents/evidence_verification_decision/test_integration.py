
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

EXAMPLES = Path("contracts/agents/v1/examples")
ROLES = (
    ("diagnostic_reasoning", "diagnosis_report"),
    ("inspection_planning", "inspection_plan_report"),
    ("inspection_quality_documentation", "inspection_quality_report"),
)


def _load(filename: str) -> dict[str, Any]:
    """Load a version-controlled contract example."""
    result: dict[str, Any] = json.loads(
        (EXAMPLES / filename).read_text(encoding="utf-8")
    )
    return result


def _request_with_reports() -> dict[str, Any]:
    """Build an Agent 8 request with registered upstream reports."""
    request = _load("evidence_verification_decision.request.json")
    registry = EvidenceRegistry.from_rows(
        request["context"], request["evidence"]
    )

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
        [
            row
            for row in request["evidence"]
            if row["kind"] != "agent_report"
        ],
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
    """Report provenance must appear in consumed evidence IDs."""
    request = _request_with_reports()
    response = _run(request)

    expected = {
        request["input"][field]["report_id"]
        for _, field in ROLES
    }

    assert expected <= set(response["consumed_evidence_ids"])


def test_registered_report_hash_matches_content() -> None:
    """Registry hashes must match the complete report content."""
    request = _request_with_reports()
    registry = {
        row["evidence_id"]: row
        for row in request["evidence"]
    }

    for _, field in ROLES:
        report = request["input"][field]
        row = registry[report["report_id"]]

        assert row["kind"] == "agent_report"
        assert row["content_sha256"] == stable_hash(report)
        assert row["source_ref"] == "report:" + report["report_id"]


def test_report_context_mismatch_is_rejected() -> None:
    """A report from another snapshot must be rejected."""
    request = _request_with_reports()
    request["input"]["diagnosis_report"]["context"]["revision"] += 1

    with pytest.raises(ValueError):
        check_request(request)


def test_report_hash_tampering_is_rejected() -> None:
    """Modified report content must invalidate its registry hash."""
    request = _request_with_reports()
    request["input"]["diagnosis_report"]["limitations"].append(
        "Tampered after registration"
    )

    with pytest.raises(ValueError):
        check_request(request)


def test_report_registration_is_deterministic() -> None:
    """Identical reports must generate identical registry records."""
    first = _request_with_reports()
    second = _request_with_reports()

    assert first == second
    assert _run(first) == _run(second)


def test_failed_diagnostic_check_is_reported_as_conflict() -> None:
    """Failed upstream diagnostic checks must create conflicts."""
    request = _request_with_reports()
    diagnosis = request["input"]["diagnosis_report"]

    diagnosis["result"]["upstream_checks"][0]["outcome"] = "fail"

    _reregister_reports(request)

    response = _run(request)

    assert any(
        row["outcome"] == "fail"
        for row in response["result"]["conflicts"]
    )


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
    """Missing inspection quality must not be silently accepted."""
    request = _request_with_reports()
    request["input"]["inspection_quality_report"] = None

    response = _run(request)

    assert response["result"]["decision_state"] == "more_evidence_required"


def test_all_decisions_remain_advisory() -> None:
    """Upstream reports must never authorize equipment actions."""
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


def test_assessment_available_with_verified_evidence() -> None:
    """Verified evidence and diagnostic candidates allow an assessment."""
    request = _registered_request_with_changes(
        diagnosis_candidates=True,
        quality_usable=True,
    )

    request["input"]["evidence_proposals"] = [
        _verified_proposal("proposal-verified-1")
    ]

    response = _run(request)
    result = response["result"]

    assert result["decision_state"] == "assessment_available"
    assert result["evidence_checks"]
    assert all(
        check["usable"] is True
        for check in result["evidence_checks"]
    )
    assert result["human_decision_required"] is True
    assert result["automatic_action_authorized"] is False
    assert result["equipment_condition_confirmed"] is False


def test_review_required_when_verified_proposals_share_roots() -> None:
    """Overlapping evidence roots must trigger human review."""
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

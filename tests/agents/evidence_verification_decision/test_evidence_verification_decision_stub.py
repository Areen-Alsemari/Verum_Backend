"""Independent behavioral tests for the evidence verification decision agent."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from verum.agents.common.validation import check_response
from verum.agents.evidence_verification_decision import (
    EvidenceVerificationDecisionAgent,
)
from verum.agents.evidence_verification_decision.evidence import check_proposal
from verum.contracts.agent_interfaces import contract_directory


def _example_request() -> dict[str, Any]:
    """Load the official contract fixture independently of the agent."""
    path = contract_directory() / "examples" / "evidence_verification_decision.request.json"
    with path.open(encoding="utf-8") as handle:
        loaded: dict[str, Any] = json.load(handle)
    return loaded


def _proposal(
    *,
    proposal_id: str = "proposal-1",
    source_ref: str = "observations:source",
    claimed_available_at_s: float | None = 100.0,
    claimed_evidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Create a proposal for isolated admission tests."""
    return {
        "proposal_id": proposal_id,
        "source_ref": source_ref,
        "claimed_available_at_s": claimed_available_at_s,
        "claimed_evidence_ids": (
            ["evidence-1"] if claimed_evidence_ids is None else claimed_evidence_ids
        ),
    }


def _registry() -> dict[str, dict[str, Any]]:
    """Create metadata-only evidence without measurement values."""
    return {
        "evidence-1": {
            "evidence_id": "evidence-1",
            "source_ref": "observations:source",
            "available_at_s": 100.0,
            "root_evidence_ids": ["evidence-1"],
        },
        "evidence-2": {
            "evidence_id": "evidence-2",
            "source_ref": "observations:source",
            "available_at_s": 100.0,
            "root_evidence_ids": ["evidence-1"],
        },
    }


def test_official_example_passes_contract() -> None:
    """Independent: validate the real agent against the official fixture."""
    request = _example_request()
    response = EvidenceVerificationDecisionAgent().run(request)

    check_response(request, response)

    assert response["agent"] == "evidence_verification_decision"
    assert response["status"] == "degraded"
    assert response["result"]["decision_state"] == "more_evidence_required"
    assert response["result"]["evidence_checks"] == []
    assert "stub" not in response["implementation"]["name"]


def test_missing_reports_require_more_evidence() -> None:
    """Independent: absent upstream reports cannot support an assessment."""
    request = _example_request()
    response = EvidenceVerificationDecisionAgent().run(request)
    result = response["result"]

    assert result["decision_state"] == "more_evidence_required"
    assert result["hypothesis_report_ids"] == []
    assert result["human_decision_required"] is True
    assert result["automatic_action_authorized"] is False
    assert result["equipment_condition_confirmed"] is False


def test_future_claim_is_rejected_without_evidence_access() -> None:
    """Independent: a future claim fails before referenced evidence is read."""
    result = check_proposal(
        _proposal(claimed_available_at_s=301.0),
        {},
        300.0,
    )

    assert result["time_admissible"] is False
    assert result["usable"] is False
    assert result["provenance_verified"] is None
    assert result["evidence_ids"] == []


def test_registered_future_evidence_is_rejected() -> None:
    """Independent: registered evidence after cutoff is not admissible."""
    registry = _registry()
    registry["evidence-1"]["available_at_s"] = 400.0

    result = check_proposal(
        _proposal(),
        registry,
        300.0,
        quality_acceptable=True,
        scope_supported=True,
    )

    assert result["time_admissible"] is False
    assert result["usable"] is False
    assert result["evidence_ids"] == []


def test_unknown_source_cannot_verify_provenance() -> None:
    """Independent: source mismatch fails provenance verification."""
    result = check_proposal(
        _proposal(source_ref="observations:wrong"),
        _registry(),
        300.0,
        quality_acceptable=True,
        scope_supported=True,
    )

    assert result["provenance_verified"] is False
    assert result["usable"] is False


def test_mixed_sources_cannot_verify_provenance() -> None:
    """Independent: every claimed evidence item must match the source."""
    registry = _registry()
    registry["evidence-2"]["source_ref"] = "observations:other"

    result = check_proposal(
        _proposal(claimed_evidence_ids=["evidence-1", "evidence-2"]),
        registry,
        300.0,
        quality_acceptable=True,
        scope_supported=True,
    )

    assert result["provenance_verified"] is False
    assert result["usable"] is False


def test_missing_evidence_identifier_is_rejected() -> None:
    """Independent: unregistered evidence cannot establish provenance."""
    result = check_proposal(
        _proposal(claimed_evidence_ids=["unknown"]),
        _registry(),
        300.0,
        quality_acceptable=True,
        scope_supported=True,
    )

    assert result["provenance_verified"] is False
    assert result["usable"] is False


def test_unknown_quality_remains_unknown() -> None:
    """Independent: source identity alone does not establish quality."""
    result = check_proposal(
        _proposal(),
        _registry(),
        300.0,
        scope_supported=True,
    )

    assert result["quality_acceptable"] is None
    assert result["usable"] is None


def test_unknown_scope_remains_unknown() -> None:
    """Independent: provenance does not establish supported scope."""
    result = check_proposal(
        _proposal(),
        _registry(),
        300.0,
        quality_acceptable=True,
    )

    assert result["scope_supported"] is None
    assert result["usable"] is None


def test_explicit_quality_failure_rejects_evidence() -> None:
    """Independent: failed quality prevents evidence admission."""
    result = check_proposal(
        _proposal(),
        _registry(),
        300.0,
        quality_acceptable=False,
        scope_supported=True,
    )

    assert result["quality_acceptable"] is False
    assert result["usable"] is False


def test_explicit_scope_failure_rejects_evidence() -> None:
    """Independent: unsupported scope prevents evidence admission."""
    result = check_proposal(
        _proposal(),
        _registry(),
        300.0,
        quality_acceptable=True,
        scope_supported=False,
    )

    assert result["scope_supported"] is False
    assert result["usable"] is False


def test_all_four_checks_must_pass() -> None:
    """Independent: positive admission requires all four verified checks."""
    result = check_proposal(
        _proposal(),
        _registry(),
        300.0,
        quality_acceptable=True,
        scope_supported=True,
    )

    assert result["time_admissible"] is True
    assert result["provenance_verified"] is True
    assert result["quality_acceptable"] is True
    assert result["scope_supported"] is True
    assert result["usable"] is True


def test_missing_claimed_time_remains_unknown() -> None:
    """Independent: unknown claimed availability is not silently accepted."""
    result = check_proposal(
        _proposal(claimed_available_at_s=None),
        _registry(),
        300.0,
        quality_acceptable=True,
        scope_supported=True,
    )

    assert result["time_admissible"] is None
    assert result["usable"] is None


def test_multiple_proposals_receive_individual_checks() -> None:
    """Independent: each proposal receives exactly one separate assessment."""
    request = _example_request()
    rows = request["evidence"]
    first = rows[0]

    request["input"]["evidence_proposals"] = [
        {
            "proposal_id": "first",
            "source_ref": first["source_ref"],
            "claimed_available_at_s": first["available_at_s"],
            "claimed_evidence_ids": [first["evidence_id"]],
        },
        {
            "proposal_id": "second",
            "source_ref": first["source_ref"],
            "claimed_available_at_s": 999.0,
            "claimed_evidence_ids": [first["evidence_id"]],
        },
    ]

    response = EvidenceVerificationDecisionAgent().run(request)
    check_response(request, response)

    checks = response["result"]["evidence_checks"]
    assert [row["proposal_id"] for row in checks] == ["first", "second"]
    assert checks[0]["quality_acceptable"] is None
    assert checks[1]["time_admissible"] is False
    assert checks[1]["evidence_ids"] == []


def test_shared_roots_are_not_independent_support() -> None:
    """Independent: two proposals with one root produce an overlap conflict."""
    request = _example_request()
    source = request["evidence"][0]

    request["input"]["evidence_proposals"] = [
        {
            "proposal_id": "first",
            "source_ref": source["source_ref"],
            "claimed_available_at_s": source["available_at_s"],
            "claimed_evidence_ids": [source["evidence_id"]],
        },
        {
            "proposal_id": "second",
            "source_ref": source["source_ref"],
            "claimed_available_at_s": source["available_at_s"],
            "claimed_evidence_ids": [source["evidence_id"]],
        },
    ]

    response = EvidenceVerificationDecisionAgent().run(request)
    check_response(request, response)

    conflicts = response["result"]["conflicts"]
    assert any(row["check_id"].startswith("shared-roots:") for row in conflicts)


def test_repeated_run_is_deterministic() -> None:
    """Independent: identical requests produce identical complete responses."""
    request = _example_request()
    original = copy.deepcopy(request)
    agent = EvidenceVerificationDecisionAgent()

    first = agent.run(request)
    second = agent.run(request)

    assert first == second
    assert request == original


@pytest.mark.parametrize(
    ("checks", "conflicts", "diagnosis", "missing_reports", "expected"),
    [
        ([], [{"evidence_ids": []}], None, [], "more_evidence_required"),
        ([{"usable": True}], [{"evidence_ids": []}], None, [], "review_required"),
        (
            [{"usable": True}],
            [],
            {
                "result": {
                    "assessment": "candidates_available",
                    "hypotheses": [{"hypothesis_id": "h1"}],
                }
            },
            [],
            "assessment_available",
        ),
    ],
)
def test_decision_precedence_adjacent_pairs(
    checks: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
    diagnosis: dict[str, Any] | None,
    missing_reports: list[str],
    expected: str,
) -> None:
    """Independent: each adjacent decision priority outranks the next state."""
    from verum.agents.evidence_verification_decision.agent import _decision

    state, _, _ = _decision(diagnosis, checks, conflicts, missing_reports)
    assert state == expected


def test_cutoff_and_noncandidate_regression() -> None:
    """Independent: cutoff is inclusive and noncandidate hypotheses are insufficient."""
    from verum.agents.evidence_verification_decision.agent import _decision

    check = check_proposal(
        _proposal(), _registry(), 100.0, quality_acceptable=True, scope_supported=True
    )
    assert check["time_admissible"] is True and check["usable"] is True
    diagnosis = {"result": {"assessment": "inconclusive", "hypotheses": [{"hypothesis_id": "h1"}]}}
    assert _decision(diagnosis, [{"usable": True}], [], [])[0] == "inconclusive"


def test_sorted_checks_and_summary_ids() -> None:
    """Independent: checks are ordered and summary lists distinct evidence IDs."""
    from verum.agents.evidence_verification_decision.agent import (
        _build_decision_result,
        _build_evidence_checks,
    )

    inputs = {
        "evidence_proposals": [_proposal(proposal_id="z"), _proposal(proposal_id="a")],
        "inspection_quality_report": None,
    }
    checks = _build_evidence_checks(inputs, _registry(), 100.0)
    assert [c["proposal_id"] for c in checks] == ["a", "z"]
    result = _build_decision_result(
        {"diagnosis_report": None}, "more_evidence_required", "Needs evidence.", [], checks, []
    )
    assert result["summary"] == "Needs evidence. Evidence IDs: evidence-1."
